"""Tenancy contract — OSS single-tenant default, Enterprise tenant-aware."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from datahek.kernel.context import RequestContext, TenantScope


@dataclass(frozen=True)
class Tenant:
    organization_id: str
    workspace_id: str | None
    project_id: str | None
    resolved_by: str


@runtime_checkable
class TenantContext(Protocol):
    async def resolve(self, ctx: RequestContext) -> Tenant: ...