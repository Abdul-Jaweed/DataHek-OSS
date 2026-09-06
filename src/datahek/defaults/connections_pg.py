"""PostgresConnectionManager — OSS opt-in persistent connection catalog.

Mirrors LocalConnectionManager semantics (CONNECTION_EXISTS / CONNECTION_NOT_FOUND
/ FORBIDDEN) while persisting rows in PostgreSQL. When `encryption_key` is set,
settings JSON is Fernet-encrypted at rest; otherwise it is stored as plain JSON.
Secret references (`secret://infisical/...`) are stored as-is and never resolved.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet

from datahek.contracts.connections import Connection
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_COLUMNS = "id, name, provider, org_id, project_id, host, port, database, settings_json"


def _derive_fernet_key(encryption_key: str) -> bytes:
    digest = hashlib.sha256(encryption_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


class PostgresConnectionManager:
    def __init__(self, pg: PgMetadata, encryption_key: str | None = None):
        self._pg = pg
        self._fernet = (
            Fernet(_derive_fernet_key(encryption_key)) if encryption_key else None
        )

    async def add(self, ctx: RequestContext, connection: Connection) -> Connection:
        conn = await self._pg.connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM connections WHERE name = %s AND org_id = %s",
                (connection.name, connection.org_id),
            ).fetchone()
            if row is not None:
                raise DatahekError(
                    ErrorCode.CONNECTION_EXISTS,
                    f"Connection '{connection.name}' already exists",
                    details={"name": connection.name},
                )
            conn.execute(
                "INSERT INTO connections (id, name, provider, org_id, project_id,"
                " host, port, database, settings_json) VALUES (%s, %s, %s, %s, %s,"
                " %s, %s, %s, %s)",
                (
                    connection.id,
                    connection.name,
                    connection.provider,
                    connection.org_id,
                    connection.project_id,
                    connection.host,
                    connection.port,
                    connection.database,
                    self._encode_settings(connection.settings),
                ),
            )
        finally:
            conn.close()
        return connection

    async def get_connection(self, ctx: RequestContext, connection_id: str) -> Connection:
        conn = await self._pg.connect()
        try:
            row = conn.execute(
                "SELECT " + _COLUMNS + " FROM connections WHERE id = %s",
                (connection_id,),
            ).fetchone()
            if row is None:
                raise DatahekError(
                    ErrorCode.CONNECTION_NOT_FOUND,
                    f"Connection '{connection_id}' not found",
                )
            found = self._row_to_connection(row)
            if found.org_id != ctx.organization_id:
                raise DatahekError(ErrorCode.FORBIDDEN, "Connection not accessible in this tenant")
            return found
        finally:
            conn.close()

    async def list_connections(self, ctx: RequestContext) -> list[Connection]:
        conn = await self._pg.connect()
        try:
            rows = conn.execute(
                "SELECT " + _COLUMNS + " FROM connections WHERE org_id = %s ORDER BY name",
                (ctx.organization_id,),
            ).fetchall()
            return [self._row_to_connection(row) for row in rows]
        finally:
            conn.close()

    async def remove(self, ctx: RequestContext, connection_id: str) -> None:
        await self.get_connection(ctx, connection_id)
        conn = await self._pg.connect()
        try:
            conn.execute(
                "DELETE FROM connections WHERE id = %s AND org_id = %s",
                (connection_id, ctx.organization_id),
            )
        finally:
            conn.close()

    def _encode_settings(self, settings: dict) -> str:
        raw = json.dumps(settings)
        if self._fernet is None:
            return raw
        return self._fernet.encrypt(raw.encode()).decode()

    def _decode_settings(self, stored: str) -> dict:
        if self._fernet is None:
            return json.loads(stored)
        try:
            return json.loads(stored)
        except ValueError:
            return json.loads(self._fernet.decrypt(stored.encode()))

    def _row_to_connection(self, row) -> Connection:
        return Connection(
            id=row[0],
            name=row[1],
            provider=row[2],
            org_id=row[3],
            project_id=row[4],
            host=row[5],
            port=row[6],
            database=row[7],
            settings=self._decode_settings(row[8]),
        )
