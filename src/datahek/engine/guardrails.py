"""Guardrail pipeline — typed decisions with deterministic ordering."""
import re
from typing import Any

from datahek.contracts.guardrails import Guardrail, GuardrailResult
from datahek.kernel.context import RequestContext


class GuardrailPipeline:
    """Runs guardrails in order; the first non-ALLOW decision wins."""

    def __init__(self, guardrails: list[Guardrail] | None = None):
        self.guardrails = list(guardrails or [])

    def add(self, guardrail: Guardrail) -> None:
        self.guardrails.append(guardrail)

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        for g in self.guardrails:
            if not g.enabled:
                continue
            result = await g.run(ctx, payload)
            if result.decision != "ALLOW":
                return result
        return GuardrailResult(decision="ALLOW", reason="ok")


class PlanReadOnlyGuardrail(Guardrail):
    name = "plan_read_only"
    stage = "plan"
    enabled = True

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        plan = payload.get("plan")
        if plan is not None and not plan.read_only:
            return GuardrailResult(
                decision="DENY",
                reason="Write operations are not allowed (read-only by default)",
                score=1.0,
            )
        return GuardrailResult(decision="ALLOW", reason="ok")


class PlanComplexityGuardrail(Guardrail):
    name = "plan_complexity"
    stage = "plan"
    enabled = True

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        plan = payload.get("plan")
        caps = payload.get("capabilities")
        if plan is None or caps is None:
            return GuardrailResult(decision="ALLOW", reason="ok")
        for node in plan.nodes:
            limit = getattr(node, "limit", None)
            max_rows = getattr(caps, "max_result_rows", 1000)
            if limit is None or limit > max_rows:
                object.__setattr__(node, "limit", max_rows)
        return GuardrailResult(decision="ALLOW", reason="limit capped")

class PolicyGuardrail(Guardrail):
    """Delegates to the PolicyEngine — table allowlists, approval gating."""

    name = "policy"
    stage = "plan"
    enabled = True

    def __init__(self, policy) -> None:
        self._policy = policy

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        plan = payload.get("plan")
        context = {
            "plan": plan,
            "table": getattr(plan.nodes[0], "source", None) if plan and plan.nodes else None,
        }
        decision = await self._policy.evaluate(context)
        action = decision.get("action", "ALLOW")
        if action == "ALLOW":
            return GuardrailResult(decision="ALLOW", reason=decision.get("reason", "ok"))
        return GuardrailResult(decision=action, reason=decision.get("reason", action), score=1.0)


class RateLimitGuardrail(Guardrail):
    """Sliding-window request limiter keyed by user — protects the LLM budget."""

    name = "rate_limit"
    stage = "input"
    enabled = True

    def __init__(self, limiter, limit: int = 60, window_s: float = 60.0) -> None:
        self._limiter = limiter
        self._limit = limit
        self._window_s = window_s

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        key = getattr(ctx, "user_id", None) or "anonymous"
        if self._limiter.allow(key, self._limit, self._window_s):
            return GuardrailResult(decision="ALLOW", reason="ok")
        return GuardrailResult(
            decision="RATE_LIMIT",
            reason=f"Rate limit exceeded ({self._limit} requests / {int(self._window_s)}s)",
            score=1.0,
        )


_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"you\s+are\s+now\s+(a|an|the)\s",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"system\s+prompt",
    r"\bdrop\s+table\b",
    r"\bdelete\s+from\b",
    r"\btruncate\s+table\b",
    r"\binsert\s+into\b",
    r"\bupdate\s+\w+\s+set\b",
    r"\balter\s+table\b",
    r"\b(grant|revoke)\s+\w+\s+on\b",
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class InputGuardrail(Guardrail):
    """Plane-1 perimeter: prompt-injection signatures, length, control chars.

    Runs before the planner reaches the LLM, and again in the execution
    pipeline (defense in depth).
    """

    name = "input"
    stage = "input"

    def __init__(self, max_chars: int | None = None) -> None:
        import os

        self.enabled = os.environ.get("DATAHEK_GUARDRAIL_INPUT", "on").lower() not in ("off", "0", "false")
        self._max_chars = max_chars or int(os.environ.get("DATAHEK_MAX_QUESTION_CHARS", "2000"))
        self._patterns = tuple(re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS)

    async def run(self, ctx: RequestContext, payload: dict) -> GuardrailResult:
        if not self.enabled:
            return GuardrailResult(decision="ALLOW", reason="ok")
        question = payload.get("question") or ""
        if not question:
            return GuardrailResult(decision="ALLOW", reason="ok")
        if len(question) > self._max_chars:
            return GuardrailResult(
                decision="DENY",
                reason=f"Question exceeds the maximum length ({self._max_chars} characters)",
                score=1.0,
            )
        if _CONTROL_CHARS.search(question):
            return GuardrailResult(decision="DENY", reason="Question contains control characters", score=1.0)
        for pattern in self._patterns:
            if pattern.search(question):
                return GuardrailResult(
                    decision="DENY",
                    reason="Prompt-injection or write-intent signature detected in the question",
                    score=1.0,
                )
        return GuardrailResult(decision="ALLOW", reason="ok")
