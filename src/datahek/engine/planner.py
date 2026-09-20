"""Planner — natural language → schema-grounded LogicalPlan (or clarification).

Per 07-agent-contracts: the planner never emits provider SQL; it produces
validated LogicalPlans. Invalid plans are retried once with model feedback,
then converted into a clarification request.
"""
import json
import logging
import re
from dataclasses import dataclass, field

from datahek.contracts.connections import Connection
from datahek.contracts.models import ModelProvider, ModelProviderError, ModelRequest
from datahek.contracts.providers import DataProvider
from datahek.contracts.secrets import SecretsProvider
from datahek.engine.executor import _resolve_secrets
from datahek.engine.plan import LogicalPlan, validate_plan
from datahek.engine.schema import SchemaCatalog, SchemaService
from datahek.kernel.context import RequestContext

logger = logging.getLogger(__name__)

MAX_TABLES_IN_PROMPT = 15
MAX_COLUMNS_IN_PROMPT = 64
MAX_PLAN_ATTEMPTS = 2

_PLAN_SYSTEM_PROMPT = """\
You are the planner of a read-only data analysis engine.
Given the user's question and the available schema, produce a JSON plan.
Return ONLY valid JSON — no markdown, no commentary.

Plan format:
{"nodes": [
  {"type": "ReadNode", "source": "<base table>", "columns": [...],
   "filter": "<optional SQL predicate>", "group_by": [...],
   "aggregates": [{"function": "<allowed function>", "column": "<column or *>", "alias": "<name>"}],
   "order_by": [...], "limit": <int>,
   "joins": [{"table": "<joined table>", "join_type": "inner|left",
              "on_left": "<base table column>", "on_right": "<joined table column>"}]}
]}

Rules:
- Read-only only. Never produce WriteNode.
- Only use tables and columns present in the schema.
- Use joins ONLY when the question spans multiple related tables (max 2 joins).
- When joining, reference joined-table columns as "table.column"; plain names target the base table.
- Only use aggregate functions allowed for the target database dialect (given below).
- Use "count_distinct" for distinct counting on SQL dialects (renders COUNT(DISTINCT col)).
- Set "limit": if the user specifies a row count, use it; otherwise default to 10.
  For grouped or time-series results, set the number of rows the result naturally needs.
- Match named entities to the column that represents them: service names belong in service-name
  columns, event categories belong in event-type columns.
- Never apply sum or avg to boolean columns; count true values with count(*) plus a WHERE condition.
- Only join columns whose types are compatible (see the schema summary); otherwise return a clarification.
- If the question is ambiguous or no table matches, return
  {"nodes": [], "clarification": "<question for the user>"}.
"""


def _dialect_prompt(dialect: str | None) -> str:
    from datahek.engine.plan import _AGGREGATE_FUNCTIONS

    if dialect in _AGGREGATE_FUNCTIONS:
        allowed = "|".join(sorted(_AGGREGATE_FUNCTIONS[dialect]))
        return f"\nTarget database dialect: {dialect}.\nAllowed aggregate functions: {allowed}"
    return ""


@dataclass(frozen=True)
class PlanResult:
    plan: LogicalPlan | None
    clarification: str | None = None
    confidence: float = 0.5
    sources_used: list[str] = field(default_factory=list)


def build_schema_summary(catalog: SchemaCatalog) -> str:
    lines = []
    for t in catalog.tables[:MAX_TABLES_IN_PROMPT]:
        visible = t.columns[:MAX_COLUMNS_IN_PROMPT]
        cols = ", ".join(f"{c.name}:{c.data_type}" for c in visible)
        hidden = len(t.columns) - len(visible)
        if hidden > 0:
            cols += f", … (+{hidden} more columns)"
        rows = f" (~{t.row_count} rows)" if t.row_count is not None else ""
        lines.append(f"- {t.name}{rows}: {cols}")
    return "\n".join(lines) or "(no tables found)"


def _normalize_join_refs(plan, catalog_columns: dict[str, set[str]]):
    """Qualify plain column refs that resolve only via a joined table.

    The model often writes "tier" (joined table) in group_by while the select
    list uses "service_meta.tier". Resolve those to the dotted form so
    validation and compilation agree.
    """
    from dataclasses import replace

    from datahek.engine.plan import ReadNode

    def resolve(col: str, base: str, joins) -> str:
        if "." in col or not joins:
            return col
        if col in catalog_columns.get(base, set()):
            return col
        matches = [j.table for j in joins if col in catalog_columns.get(j.table, set())]
        if len(matches) == 1:
            return f"{matches[0]}.{col}"
        return col

    nodes = []
    for node in plan.nodes:
        if not isinstance(node, ReadNode) or not node.joins:
            nodes.append(node)
            continue
        nodes.append(replace(
            node,
            columns=[resolve(c, node.source, node.joins) for c in node.columns],
            group_by=[resolve(c, node.source, node.joins) for c in node.group_by],
            aggregates=[replace(a, column=resolve(a.column, node.source, node.joins))
                        if a.column != "*" else a for a in node.aggregates],
        ))
    return plan.__class__(version=plan.version, nodes=nodes)


def _format_metrics(metrics: list[dict], question: str, limit: int = 10) -> str:
    """Render the semantic layer for the planner: catalog metrics, relevance first."""
    if not metrics:
        return ""
    question_lower = question.lower()
    ordered = sorted(
        metrics,
        key=lambda m: (
            m.get("name", "").lower() not in question_lower
            and m.get("description", "").lower() not in question_lower,
            m.get("name", ""),
        ),
    )[:limit]
    lines = ["Metric definitions (semantic layer — prefer these when relevant, keep the alias):"]
    for m in ordered:
        expr = f"{m.get('aggregate')}({m.get('column')})"
        if m.get("filter"):
            expr += f" WHERE {m['filter']}"
        line = f"- {m.get('name')}: {expr} on {m.get('table')}"
        if m.get("description"):
            line += f' — "{m["description"]}"'
        lines.append(line)
    return "\n".join(lines)


def _tolerant_json_text(content: str) -> str:
    """Strip markdown fences and repair the most common LLM JSON slips."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # trailing commas before } or ] — the single most common model slip
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _literal_eval_fallback(text: str) -> dict | None:
    """Accept Python-style dicts ('single quotes', True/False/None) safely."""
    import ast

    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _dialect_of(provider) -> str | None:
    capabilities = getattr(provider, "capabilities", None)
    return getattr(capabilities, "dialect", None)


def _format_history(history: list[dict] | None, max_chars: int = 2000,
                    per_message: int = 300) -> str:
    """Compact recent conversation turns for the planner prompt."""
    if not history:
        return ""
    lines: list[str] = []
    total = 0
    for message in history:
        role = "User" if message.get("role") == "user" else "Assistant"
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        content = content[:per_message]
        line = f"{role}: {content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


class Planner:
    def __init__(self, model: ModelProvider, schema_service: SchemaService,
                 max_attempts: int = MAX_PLAN_ATTEMPTS, skills=None,
                 secrets: SecretsProvider | None = None, metrics=None):
        self._model = model
        self._schema_service = schema_service
        self._max_attempts = max_attempts
        self._skills = skills
        self._secrets = secrets
        self._metrics = metrics

    async def plan(
        self,
        question: str,
        ctx: RequestContext,
        connection: Connection,
        provider: DataProvider,
        extra_prompt: str | None = None,
        history: list[dict] | None = None,
    ) -> PlanResult:
        from datahek.engine.guardrails import InputGuardrail
        from datahek.kernel.errors import DatahekError, ErrorCode

        input_check = await InputGuardrail().run(ctx, {"question": question})
        if input_check.decision != "ALLOW":
            raise DatahekError(ErrorCode.QUERY_DENIED, input_check.reason,
                               details={"decision": input_check.decision, "stage": "input"})

        if self._secrets is not None:
            connection = await _resolve_secrets(connection, self._secrets)
        catalog = await self._schema_service.get_catalog(ctx, connection, provider)
        tables = self._schema_service.tables(catalog)
        columns = self._schema_service.columns(catalog)
        schema_summary = build_schema_summary(catalog)

        skill_prompt = ""
        if self._skills is not None:
            from datahek.engine.skills import build_skill_prompt
            skill_prompt = build_skill_prompt(self._skills.match(question, catalog))

        metric_block = ""
        if self._metrics is not None:
            try:
                metric_block = _format_metrics(await self._metrics.list(ctx), question)
            except Exception as exc:
                logger.warning("Metric catalog unavailable: %s", exc)

        feedback = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._model.complete(
                    self._build_request(question, schema_summary, feedback, skill_prompt,
                                        extra_prompt, _dialect_of(provider), history, metric_block))
            except ModelProviderError as e:
                from datahek.kernel.errors import DatahekError, ErrorCode
                if e.status_code == 429:
                    raise DatahekError(ErrorCode.RATE_LIMITED, "Model provider rate limited") from e
                raise DatahekError(ErrorCode.MODEL_UNAVAILABLE, "Model provider unavailable") from e
            parsed, clarification = self._parse(response.content)
            if clarification:
                return PlanResult(plan=None, clarification=clarification, confidence=0.3)
            if parsed is None:
                return PlanResult(plan=None, clarification="I could not interpret the request into a data plan.", confidence=0.2)
            try:
                parsed = _normalize_join_refs(parsed, columns)
                validate_plan(parsed, tables, columns, dialect=_dialect_of(provider),
                              column_types=self._schema_service.column_types(catalog))
                sources: list[str] = []
                for n in parsed.nodes:
                    if hasattr(n, "source"):
                        sources.append(n.source)
                        sources.extend(j.table for j in getattr(n, "joins", []) or [])
                return PlanResult(plan=parsed, confidence=0.8, sources_used=sources)
            except Exception as e:
                feedback = f"The previous plan was invalid: {e}. Fix the plan."
                logger.warning("Planner attempt %d invalid: %s", attempt + 1, e)

        return PlanResult(
            plan=None,
            clarification="The schema does not support this question as stated. Please rephrase or choose different tables.",
            confidence=0.2,
        )

    @staticmethod
    def _build_request(question: str, schema_summary: str, feedback: str | None,
                       skill_prompt: str = "", extra_prompt: str | None = None,
                       dialect: str | None = None,
                       history: list[dict] | None = None,
                       metric_block: str = "") -> ModelRequest:
        system = _PLAN_SYSTEM_PROMPT + _dialect_prompt(dialect)
        history_block = _format_history(history)
        if history_block:
            user = (f"Conversation so far:\n{history_block}\n\n"
                    f"Question: {question}\n\nSchema:\n{schema_summary}")
        else:
            user = f"Question: {question}\n\nSchema:\n{schema_summary}"
        if metric_block:
            user += f"\n\n{metric_block}"
        if skill_prompt:
            user += f"\n\n{skill_prompt}"
        if extra_prompt:
            user += f"\n\nAdditional guidance:\n{extra_prompt}"
        if feedback:
            user += f"\n\nFeedback: {feedback}"
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "response_format": "json_object",
        }

    @staticmethod
    def _parse(content: str) -> tuple[LogicalPlan | None, str | None]:
        text = _tolerant_json_text(content)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = _literal_eval_fallback(text)
            if data is None:
                return None, None
        if not isinstance(data, dict):
            return None, None
        if data.get("clarification"):
            return None, str(data["clarification"])
        for node in data.get("nodes", []):
            if isinstance(node, dict) and isinstance(node.get("filter"), str):
                node["filter"] = node["filter"].replace("==", "=")
        try:
            return LogicalPlan.from_dict(data), None
        except Exception:
            return None, None