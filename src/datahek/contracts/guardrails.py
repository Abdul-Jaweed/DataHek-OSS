"""Guardrail contract — typed decisions, never arbitrary exceptions."""
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

GuardrailDecision = Literal["ALLOW", "DENY", "REDACT", "MASK", "REQUIRE_APPROVAL",
                            "RATE_LIMIT", "FILTER"]

GuardrailStage = Literal["input", "plan", "sql", "output"]


@dataclass(frozen=True)
class GuardrailResult:
    decision: GuardrailDecision
    reason: str = ""
    score: float | None = None
    evidence: dict = field(default_factory=dict)
    policy_version: str | None = None


@runtime_checkable
class Guardrail(Protocol):
    name: str
    stage: GuardrailStage
    enabled: bool

    async def run(self, ctx: Any, payload: dict) -> GuardrailResult: ...