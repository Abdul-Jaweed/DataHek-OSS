"""MultiStepAnalyst — supervisor-lite decomposition for complex questions.

Lifecycle B from the prototype: a complex question is decomposed into a few
sub-questions, each planned AND executed through the identical guarded
pipeline (validation, policy, audit), then synthesized into one answer.

Deliberately NOT a peer-to-peer multi-agent mesh: sequential steps through
the same deterministic engine — the safety properties never change.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

_COMPLEX_HINTS = re.compile(
    r"\b(compare|versus|vs\.?|trend|over time|correlate|correlation|why|"
    r"breakdown|per (month|week|day|region|service)|between .+ and|"
    r"increase|decrease|drop|growth)\b",
    re.IGNORECASE,
)

_DECOMPOSE_PROMPT = """\
You decompose analytical questions into independent sub-questions for a
read-only SQL engine. Return ONLY JSON:
{"complex": true|false, "steps": ["<sub-question>", ...]}
Rules:
- Single-fact questions (a count, a list, one aggregate): {"complex": false, "steps": []}
- Comparative or multi-part questions: 2-4 self-contained sub-questions.
"""

_SYNTHESIS_PROMPT = """\
You are an analyst. Given the user's original question and the results of
several executed sub-queries, write a concise combined answer grounded ONLY
in the provided numbers. Note any contradiction or missing part briefly.
"""


class MultiStepAnalyst:
    def __init__(self, model, planner, engine, reasoner, max_steps: int = 3) -> None:
        self._model = model
        self._planner = planner
        self._engine = engine
        self._reasoner = reasoner
        self._max_steps = max_steps

    @staticmethod
    def looks_complex(question: str) -> bool:
        return len(question) > 120 or bool(_COMPLEX_HINTS.search(question))

    async def decompose(self, question: str, connected_hint: str = "") -> list[str]:
        """Return sub-questions, or [] when the question is single-step."""
        response = await self._model.complete({
            "messages": [
                {"role": "system", "content": _DECOMPOSE_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0,
            "response_format": "json_object",
        })
        try:
            data = json.loads(response.content)
        except Exception:
            return []
        if not data.get("complex"):
            return []
        steps = [str(s) for s in (data.get("steps") or []) if str(s).strip()]
        return steps[: self._max_steps]

    async def run(self, question: str, ctx, conn, provider) -> tuple[list[dict], str] | None:
        """Decompose + execute every step; returns (step_results, synthesis) or None."""
        steps = await self.decompose(question)
        if len(steps) < 2:
            return None

        from datahek.engine.compile import compile_sql

        results: list[dict] = []
        for step in steps:
            plan_result = await self._planner.plan(step, ctx, conn, provider)
            if plan_result.clarification or plan_result.plan is None:
                results.append({"question": step, "error": plan_result.clarification or "no plan"})
                continue
            result = await self._engine.execute(ctx, plan_result.plan, conn)
            columns = [c["name"] for c in result.columns]
            results.append({
                "question": step,
                "columns": columns,
                "rows": [dict(zip(columns, row)) for row in result.rows[:20]],
                "row_count": result.row_count,
                "sql": compile_sql(plan_result.plan),
            })

        synthesis = await self._synthesize(question, results)
        return results, synthesis

    async def _synthesize(self, question: str, results: list[dict]) -> str:
        payload = json.dumps(results, default=str)[:6000]
        try:
            response = await self._model.complete({
                "messages": [
                    {"role": "system", "content": _SYNTHESIS_PROMPT},
                    {"role": "user", "content": f"Original question: {question}\n\nStep results:\n{payload}"},
                ],
                "temperature": 0.2,
            })
            return response.content.strip()
        except Exception as exc:
            logger.warning("Synthesis failed; using step summary: %s", exc)
            return "; ".join(
                f"{r['question']} → {r.get('row_count', 'n/a')} rows"
                for r in results
            )
