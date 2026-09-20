"""PostgreSQL ContextRegistry + ContextStore — durable context metadata (opt-in)."""
import dataclasses
import json
from datetime import datetime, timezone

from datahek.context import lifecycle, serialization
from datahek.contracts.context import (
    ArtifactKind,
    ContextArtifact,
    ContextPackage,
    ContextRecord,
    LifecycleState,
)
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_RECORD_COLUMNS = ("context_id, org_id, project_id, connection_id, scope, version,"
                   " state, schema_hash, record_json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresContextRegistry:
    def __init__(self, pg):
        self._pg = pg

    async def register(self, ctx: RequestContext, record: ContextRecord) -> str:
        if record.org_id != ctx.organization_id:
            raise DatahekError(
                ErrorCode.FORBIDDEN,
                "Context record belongs to another tenant",
                details={"org_id": record.org_id})
        connection = await self._pg.connect()
        try:
            connection.execute(
                "INSERT INTO context_records (" + _RECORD_COLUMNS + ") VALUES"
                " (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (context_id) DO UPDATE SET org_id = EXCLUDED.org_id,"
                " project_id = EXCLUDED.project_id, connection_id = EXCLUDED.connection_id,"
                " scope = EXCLUDED.scope, version = EXCLUDED.version,"
                " state = EXCLUDED.state, schema_hash = EXCLUDED.schema_hash,"
                " record_json = EXCLUDED.record_json",
                (record.context_id, record.org_id, record.project_id, record.connection_id,
                 record.scope, record.version, record.state.value, record.schema_hash,
                 json.dumps(serialization.record_to_dict(record))))
        finally:
            connection.close()
        return record.context_id

    async def get(self, ctx: RequestContext, context_id: str) -> ContextRecord | None:
        connection = await self._pg.connect()
        try:
            row = connection.execute(
                "SELECT record_json FROM context_records WHERE context_id = %s"
                " AND org_id = %s", (context_id, ctx.organization_id)).fetchone()
        finally:
            connection.close()
        return serialization.record_from_dict(json.loads(row[0])) if row else None

    async def find(self, ctx: RequestContext, *, connection_id: str,
                   scope: str | None = None,
                   state: LifecycleState | None = None) -> list[ContextRecord]:
        query = ("SELECT record_json FROM context_records WHERE org_id = %s"
                 " AND connection_id = %s")
        params: list = [ctx.organization_id, connection_id]
        if scope is not None:
            query += " AND scope = %s"
            params.append(scope)
        if state is not None:
            query += " AND state = %s"
            params.append(state.value)
        query += " ORDER BY version DESC"
        connection = await self._pg.connect()
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        return [serialization.record_from_dict(json.loads(row[0])) for row in rows]

    async def active(self, ctx: RequestContext, *, connection_id: str,
                     scope: str) -> ContextRecord | None:
        connection = await self._pg.connect()
        try:
            row = connection.execute(
                "SELECT record_json FROM context_records WHERE org_id = %s"
                " AND connection_id = %s AND scope = %s AND state = %s"
                " ORDER BY version DESC LIMIT 1",
                (ctx.organization_id, connection_id, scope,
                 LifecycleState.ACTIVE.value)).fetchone()
        finally:
            connection.close()
        return serialization.record_from_dict(json.loads(row[0])) if row else None

    async def set_state(self, ctx: RequestContext, context_id: str,
                        state: LifecycleState, reason: str = "") -> None:
        record = await self.get(ctx, context_id)
        if record is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Context '{context_id}' not found")
        lifecycle.assert_transition(record.state, state)
        updated = dataclasses.replace(record, state=state, updated_at=_now())
        connection = await self._pg.connect()
        try:
            connection.execute(
                "UPDATE context_records SET state = %s, record_json = %s"
                " WHERE context_id = %s AND org_id = %s",
                (state.value, json.dumps(serialization.record_to_dict(updated)),
                 context_id, ctx.organization_id))
        finally:
            connection.close()

    async def invalidate(self, ctx: RequestContext, *, connection_id: str,
                         reason: str) -> int:
        marked = 0
        for record in await self.find(ctx, connection_id=connection_id, state=None):
            if record.state in (LifecycleState.SUPERSEDED, LifecycleState.STALE):
                continue
            if not lifecycle.is_transition_allowed(record.state, LifecycleState.STALE):
                continue
            updated = dataclasses.replace(record, state=LifecycleState.STALE,
                                          updated_at=_now(),
                                          notes=reason[:200] or record.notes)
            connection = await self._pg.connect()
            try:
                connection.execute(
                    "UPDATE context_records SET state = %s, record_json = %s"
                    " WHERE context_id = %s AND org_id = %s",
                    (LifecycleState.STALE.value,
                     json.dumps(serialization.record_to_dict(updated)),
                     record.context_id, ctx.organization_id))
            finally:
                connection.close()
            marked += 1
        return marked

    async def versions(self, ctx: RequestContext, *, connection_id: str,
                       scope: str) -> list[ContextRecord]:
        return await self.find(ctx, connection_id=connection_id, scope=scope)


class PostgresContextStore:
    def __init__(self, pg):
        self._pg = pg

    async def _owns_record(self, ctx: RequestContext, context_id: str) -> bool:
        connection = await self._pg.connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM context_records WHERE context_id = %s AND org_id = %s",
                (context_id, ctx.organization_id)).fetchone()
        finally:
            connection.close()
        return row is not None

    async def put(self, ctx: RequestContext, context_id: str,
                  artifact: ContextArtifact) -> None:
        if not await self._owns_record(ctx, context_id):
            raise DatahekError(ErrorCode.NOT_FOUND, f"Context '{context_id}' not found")
        connection = await self._pg.connect()
        try:
            connection.execute(
                "INSERT INTO context_artifacts (context_id, kind, org_id, payload_json)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (context_id, kind) DO UPDATE"
                " SET org_id = EXCLUDED.org_id, payload_json = EXCLUDED.payload_json",
                (context_id, artifact.envelope.kind.value, ctx.organization_id,
                 json.dumps(serialization.artifact_to_dict(artifact))))
        finally:
            connection.close()

    async def get(self, ctx: RequestContext, context_id: str,
                  kind: ArtifactKind) -> ContextArtifact | None:
        connection = await self._pg.connect()
        try:
            row = connection.execute(
                "SELECT payload_json FROM context_artifacts WHERE context_id = %s"
                " AND kind = %s AND org_id = %s",
                (context_id, kind.value, ctx.organization_id)).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return serialization.artifact_from_dict(kind, json.loads(row[0]))

    async def put_package(self, ctx: RequestContext, context_id: str,
                          package: ContextPackage) -> None:
        if not await self._owns_record(ctx, context_id):
            raise DatahekError(ErrorCode.NOT_FOUND, f"Context '{context_id}' not found")
        connection = await self._pg.connect()
        try:
            connection.execute(
                "INSERT INTO context_packages (context_id, org_id, payload_json)"
                " VALUES (%s, %s, %s) ON CONFLICT (context_id) DO UPDATE"
                " SET org_id = EXCLUDED.org_id, payload_json = EXCLUDED.payload_json",
                (context_id, ctx.organization_id,
                 json.dumps(serialization.package_to_dict(package))))
        finally:
            connection.close()

    async def get_package(self, ctx: RequestContext,
                          context_id: str) -> ContextPackage | None:
        connection = await self._pg.connect()
        try:
            row = connection.execute(
                "SELECT payload_json FROM context_packages WHERE context_id = %s"
                " AND org_id = %s", (context_id, ctx.organization_id)).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return serialization.package_from_dict(json.loads(row[0]))
