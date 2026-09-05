"""SingleTenantContext — OSS default: implicit default org/project."""
from datahek.contracts.tenancy import Tenant, TenantContext
from datahek.kernel.context import RequestContext


class SingleTenantContext(TenantContext):
    async def resolve(self, ctx: RequestContext) -> Tenant:
        return Tenant(
            organization_id="default",
            workspace_id=None,
            project_id="default",
            resolved_by="default",
        )