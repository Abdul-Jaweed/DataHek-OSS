"""Reasoner contract — natural-language explanation of query results."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Reasoner(Protocol):
    async def explain(self, question: str, result: object, plan: object, ctx: object) -> str: ...