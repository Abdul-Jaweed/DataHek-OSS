"""Verifier contract — independent post-execution answer checking."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Verifier(Protocol):
    async def verify(self, question: str, result: object, ctx: object) -> dict: ...
