"""Request context — normalized across API, CLI, UI, MCP, SDK, and workers."""
from dataclasses import dataclass, field
from typing import Literal

from datahek.kernel import ids

Source = Literal["api", "cli", "ui", "mcp", "sdk", "worker"]
ResolvedBy = Literal["header", "token", "api_key", "mcp_client", "default"]


@dataclass(frozen=True)
class TenantScope:
    organization_id: str = "default"
    workspace_id: str | None = None
    project_id: str | None = "default"
    resolved_by: ResolvedBy = "default"


@dataclass(frozen=True)
class RequestContext:
    """The single context every entry point must produce."""

    request_id: str = field(default_factory=ids.new_id)
    trace_id: str | None = None
    user_id: str = "anonymous"
    organization_id: str = "default"
    workspace_id: str | None = None
    project_id: str = "default"
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    connection_id: str | None = None
    approval_id: str | None = None
    question: str | None = None
    source: Source = "api"
    authenticated: bool = False
    entitlements: frozenset[str] = field(default_factory=frozenset)

    @property
    def tenant_scope(self) -> TenantScope:
        return TenantScope(
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
        )