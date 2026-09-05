"""LocalPolicyEngine — OSS default: simple table allowlists.

Enterprise replaces this with a versioned, tenant-aware policy engine.
"""
from datahek.contracts.policy import PolicyDecision, PolicyEngine


class LocalPolicyEngine(PolicyEngine):
    def __init__(self, allowed_tables: list[str] | None = None):
        self._allowed = set(allowed_tables or [])

    async def evaluate(self, context: dict) -> PolicyDecision:
        table = context.get("table")
        if table is not None and table not in self._allowed:
            return {"action": "DENY", "reason": f"table '{table}' not allowed", "policy_version": "oss:1"}
        return {"action": "ALLOW", "reason": "ok", "policy_version": "oss:1"}