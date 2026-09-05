"""Reasoner — natural-language explanation of normalized query results.

The model only ever sees the result summary; fallback text guarantees the
API never fails because the explanation model is down.
"""
import logging

from datahek.contracts.models import ModelProvider
from datahek.contracts.reasoner import Reasoner
from datahek.engine.executor import QueryResult
from datahek.engine.plan import LogicalPlan
from datahek.kernel.context import RequestContext

logger = logging.getLogger(__name__)

_EXPLAIN_SYSTEM_PROMPT = """\
You are a concise data analyst.
Explain the query result in plain language, addressing the user's question.
Rules:
- Only reference data that is present in the result. Never invent numbers.
- Keep it short (2-4 sentences) unless the user asks for detail.
- No markdown tables unless helpful.
"""


def fallback_summary(result: QueryResult) -> str:
    if not result.rows:
        return "No rows returned."
    columns = [c["name"] for c in result.columns]
    head = ", ".join(columns)
    return f"{result.row_count} rows returned: {head}"


class ModelReasoner(Reasoner):
    def __init__(self, model: ModelProvider, max_rows_in_prompt: int = 20):
        self._model = model
        self._max_rows = max_rows_in_prompt

    async def explain(self, question: str, result: QueryResult, plan: LogicalPlan, ctx: RequestContext) -> str:
        columns = [c["name"] for c in result.columns]
        rows = result.rows[: self._max_rows]
        rows_text = "\n".join(
            ", ".join(str(v) for v in row) for row in rows
        ) or "(empty)"
        truncated = len(result.rows) > self._max_rows

        source = ", ".join(n.source for n in plan.nodes if hasattr(n, "source"))
        user = (
            f"Question: {question}\n"
            f"Source: {source or 'unknown'}\n"
            f"Columns: {', '.join(columns)}\n"
            f"Rows ({result.row_count}{' truncated in view' if truncated else ''}):\n{rows_text}"
        )
        try:
            response = await self._model.complete({
                "messages": [
                    {"role": "system", "content": _EXPLAIN_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            })
            return response.content.strip() or fallback_summary(result)
        except Exception as e:
            logger.warning("Explanation model failed; using fallback: %s", e)
            return fallback_summary(result)