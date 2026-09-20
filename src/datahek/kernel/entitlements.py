"""Entitlements — limits are defaults, never hardcoded restrictions.

Implements the EntitlementService contract: commercial limits flow through
this layer, never through scattered feature checks.
"""
from dataclasses import dataclass, fields

from datahek.kernel.context import RequestContext

_OSS_LIMITS: dict[str, int] = {
    "mcp.servers": 3,
    "prompt.templates": 3,
    "connections": 5,
    "projects": 1,
    "users": 5,
    "evaluation.datasets": 3,
}


@dataclass(frozen=True)
class ResourceLimits:
    mcp_servers: int = 3
    prompt_templates: int = 3
    connections: int = 5
    projects: int = 1
    users: int = 5
    evaluation_datasets: int = 3

    def to_dict(self) -> dict[str, int]:
        return {f.name.replace("_", "."): getattr(self, f.name) for f in fields(self)}


class EntitlementProvider:
    """OSS default entitlement provider — static limits.

    Replace with a subscription/contract provider in Production/Enterprise.
    """

    def __init__(self, limits: dict[str, int] | ResourceLimits | None = None):
        self._limits = dict(_OSS_LIMITS)
        if isinstance(limits, ResourceLimits):
            self._limits.update(limits.to_dict())
        elif isinstance(limits, dict):
            self._limits.update(limits)

    def limit(self, capability: str) -> int | None:
        return self._limits.get(capability)

    def all_limits(self) -> dict[str, int]:
        return dict(self._limits)

    def allows(self, capability: str, current: int) -> bool:
        """Creation-time check: is the current count within the configured limit?"""
        limit = self._limits.get(capability)
        if limit is None:
            return True
        return current <= limit

    async def check(self, ctx: RequestContext, capability: str) -> bool:
        """Contract: the capability is available under this provider's edition."""
        return True

    async def limits(self, ctx: RequestContext, resource: str) -> dict[str, int]:
        """Contract: configured limits for a resource family."""
        prefix = f"{resource}."
        return {k: v for k, v in self._limits.items() if k == resource or k.startswith(prefix)}