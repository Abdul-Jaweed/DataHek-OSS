"""LocalConnectionManager — OSS default: in-memory connection catalog."""
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode


class LocalConnectionManager(ConnectionManager):
    def __init__(self, connections: list[Connection] | None = None):
        self._connections = {c.id: c for c in (connections or [])}

    async def add(self, ctx: RequestContext, connection: Connection) -> Connection:
        if any(c.name == connection.name for c in self._connections.values()):
            raise DatahekError(
                ErrorCode.CONNECTION_EXISTS,
                f"Connection '{connection.name}' already exists",
                details={"name": connection.name},
            )
        self._connections[connection.id] = connection
        return connection

    async def get_connection(self, ctx: RequestContext, connection_id: str) -> Connection:
        conn = self._connections.get(connection_id)
        if conn is None:
            raise DatahekError(ErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found")
        if conn.org_id != ctx.organization_id:
            raise DatahekError(ErrorCode.FORBIDDEN, "Connection not accessible in this tenant")
        return conn

    async def list_connections(self, ctx: RequestContext) -> list[Connection]:
        return [c for c in self._connections.values() if c.org_id == ctx.organization_id]