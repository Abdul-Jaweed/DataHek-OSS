"""Policy engine contract — middleware asks; the engine decides."""
from typing import Protocol, TypedDict, runtime_checkable


class PolicyDecision(TypedDict):
    action: str
    reason: str
    policy_version: str


@runtime_checkable
class PolicyEngine(Protocol):
    async def evaluate(self, context: dict) -> PolicyDecision: ...