"""FollowUpSuggester — proposes next questions after an answer (opt-in).

One small LLM call; fails open to an empty list so it can never break a
request. Disabled by default (DATAHEK_SUGGESTIONS=on to enable).
"""
import json
import logging

logger = logging.getLogger(__name__)

_SUGGEST_PROMPT = """\
You suggest follow-up questions for a data analysis session.
Given the user's question and a summary of the result, propose 3 short,
specific follow-up questions a data analyst would naturally ask next.
Reply with ONLY JSON: {"suggestions": ["...", "...", "..."]}
"""


class FollowUpSuggester:
    def __init__(self, model) -> None:
        self._model = model

    @staticmethod
    def _summary(result) -> str:
        columns = [c["name"] for c in getattr(result, "columns", [])]
        rows = getattr(result, "rows", []) or []
        return "columns: {}\nrow_count: {}\nsample: {}".format(
            columns, getattr(result, "row_count", len(rows)), rows[:3])

    async def suggest(self, question: str, result, ctx) -> list[str]:
        try:
            response = await self._model.complete({
                "messages": [
                    {"role": "system", "content": _SUGGEST_PROMPT},
                    {"role": "user", "content": "Question: {}\n\nResult:\n{}".format(
                        question, self._summary(result))},
                ],
                "temperature": 0.3,
                "response_format": "json_object",
            })
            data = json.loads(response.content)
            items = [str(s).strip() for s in (data.get("suggestions") or []) if str(s).strip()]
            return items[:3]
        except Exception as exc:
            logger.warning("Follow-up suggestions unavailable: %s", exc)
            return []
