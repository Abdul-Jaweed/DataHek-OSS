"""Connection contract — the agent only asks for a connection by id."""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from datahek.contracts.secrets import SecretRef
from datahek.kernel.context import RequestContext


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    provider: str
    org_id: str
    project_id: str
    secret_ref: SecretRef | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    settings: dict = field(default_factory=dict)


@runtime_checkable
class ConnectionManager(Protocol):
    async def get_connection(self, ctx: RequestContext, connection_id: str) -> Connection: ...
    async def list_connections(self, ctx: RequestContext) -> list[Connection]: ...
    async def add(self, ctx: RequestContext, connection: Connection) -> Connection: ...
    async def remove(self, ctx: RequestContext, connection_id: str) -> None: ...