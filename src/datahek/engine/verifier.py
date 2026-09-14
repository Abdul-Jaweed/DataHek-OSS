"""ModelVerifier — independent check that the result answers the question.

Sees ONLY the question and a result summary (never the planner's reasoning),
mirroring the independent-verifier principle: no context contamination.
Fails open (ok=True) on any model/parse failure — verification must never
break an answer.
"""
import json
import logging

logger = logging.getLogger(__name__)

_VERIFY_PROMPT = """\
You are an independent verifier of data answers.
Given a user question and a summary of the query result, decide whether the
result plausibly answers the question.
Reply with ONLY JSON: {"ok": true|false, "note": "<one short sentence>"}
"""


class ModelVerifier:
    def __init__(self, model) -> None:
        self._model = model

    def _summary(self, result) -> str:
        columns = [c["name"] for c in getattr(result, "columns", [])]
        rows = getattr(result, "rows", []) or []
        sample = rows[:5]
        row_count = getattr(result, "row_count", len(rows))
        return "columns: {}\nrow_count: {}\nsample: {}".format(columns, row_count, sample)

    async def verify(self, question: str, result, ctx) -> dict:
        try:
            response = await self._model.complete({
                "messages": [
                    {"role": "system", "content": _VERIFY_PROMPT},
                    {"role": "user", "content": "Question: {}\n\nResult:\n{}".format(
                        question, self._summary(result))},
                ],
                "temperature": 0.0,
                "response_format": "json_object",
            })
            verdict = json.loads(response.content)
            return {"ok": bool(verdict.get("ok", True)), "note": str(verdict.get("note", ""))[:300]}
        except Exception as exc:
            logger.warning("Verification unavailable; passing through: %s", exc)
            return {"ok": True, "note": "verification unavailable"}
