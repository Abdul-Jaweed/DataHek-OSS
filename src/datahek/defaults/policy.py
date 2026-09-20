"""LocalPolicyEngine — OSS default: table allowlists + human-approval gating.

Enterprise replaces this with a versioned, tenant-aware policy engine.
"""
import os

from datahek.contracts.policy import PolicyDecision, PolicyEngine

_DEFAULT_SENSITIVE = ("credential", "password", "secret", "salary", "salaries", "pii")


class LocalPolicyEngine(PolicyEngine):
    def __init__(self, allowed_tables: list[str] | None = None,
                 sensitive_patterns: list[str] | None = None,
                 approval_row_limit: int | None = None):
        self._allowed = set(allowed_tables or [])
        if sensitive_patterns is None:
            env = os.environ.get("DATAHEK_APPROVAL_SENSITIVE_TABLES", "")
            sensitive_patterns = [p.strip() for p in env.split(",") if p.strip()] or list(_DEFAULT_SENSITIVE)
        self._sensitive = tuple(p.lower() for p in sensitive_patterns)
        if approval_row_limit is None:
            approval_row_limit = int(os.environ.get("DATAHEK_APPROVAL_ROW_LIMIT", "1000"))
        self._approval_row_limit = approval_row_limit

    def _requires_approval(self, context: dict) -> str | None:
        plan = context.get("plan")
        nodes = getattr(plan, "nodes", None) or []
        for node in nodes:
            sources = [getattr(node, "source", "")] + [j.table for j in getattr(node, "joins", []) or []]
            for source in sources:
                lowered = str(source).lower()
                if any(p in lowered for p in self._sensitive):
                    return f"table '{source}' matches a sensitive-table policy"
            source = getattr(node, "source", "")
            limit = getattr(node, "limit", None)
            if limit is not None and limit > self._approval_row_limit:
                return f"row limit {limit} exceeds the approval threshold ({self._approval_row_limit})"
            if limit is None and not getattr(node, "aggregates", None):
                return f"unbounded scan of '{source}' without a row limit"
        return None

    async def evaluate(self, context: dict) -> PolicyDecision:
        tables = context.get("tables") or ([context["table"]] if context.get("table") else [])
        if self._allowed:
            for table in tables:
                if table not in self._allowed:
                    return {"action": "DENY", "reason": f"table '{table}' not allowed",
                            "policy_version": "oss:1"}
        approval_reason = self._requires_approval(context)
        if approval_reason is not None:
            return {"action": "REQUIRE_APPROVAL", "reason": approval_reason, "policy_version": "oss:1"}
        return {"action": "ALLOW", "reason": "ok", "policy_version": "oss:1"}