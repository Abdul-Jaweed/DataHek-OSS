"""Capability model — edition detection without scattered ``if enterprise:`` checks."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    sso: bool = False
    multi_tenancy: bool = False
    advanced_rbac: bool = False
    policy_engine: bool = False
    centralized_audit: bool = False
    usage_analytics: bool = False
    high_availability: bool = False

    def supports(self, capability: str) -> bool:
        return bool(getattr(self, capability, False))


OSS_CAPABILITIES = Capabilities()
ENTERPRISE_CAPABILITIES = Capabilities(
    sso=True,
    multi_tenancy=True,
    advanced_rbac=True,
    policy_engine=True,
    centralized_audit=True,
    usage_analytics=True,
    high_availability=True,
)