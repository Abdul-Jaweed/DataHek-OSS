"""SQLite ContextRegistry + ContextStore — OSS default durable context metadata.

Records carry lifecycle/version/hash; artifacts and compiled packages are stored
as typed JSON payloads keyed by context id. Every read is tenant-scoped.
"""
import asyncio
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from datahek.context import lifecycle, serialization
from datahek.contracts.context import ArtifactKind, ContextArtifact, ContextPackage, ContextRecord, LifecycleState
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_records (
  context_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  version INTEGER NOT NULL,
  state TEXT NOT NULL,
  schema_hash TEXT NOT NULL,
  record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_records_scope
  ON context_records(org_id, connection_id, scope, version);
CREATE TABLE IF NOT EXISTS context_artifacts (
  context_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  org_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (context_id, kind)
);
CREATE TABLE IF NOT EXISTS context_packages (
  context_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
"""


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class _SqliteBase:
    def __init__(self, path: str | None = None):
        self._path = str(path or os.environ.get("DATAHEK_DB_PATH", "datahek.db"))
        connection = sqlite3.connect(self._path)
        try:
            connection.executescript(_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection


def _decode_record(row) -> ContextRecord:
    return serialization.record_from_dict(json.loads(row["record_json"]))


class SqliteContextRegistry(_SqliteBase):
    def _register(self, ctx: RequestContext, record: ContextRecord) -> str:
        if record.org_id != ctx.organization_id:
            raise DatahekError(
                ErrorCode.FORBIDDEN,
                "Context record belongs to another tenant",
                details={"org_id": record.org_id})
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO context_records (context_id, org_id, project_id,"
                " connection_id, scope, version, state, schema_hash, record_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.context_id, record.org_id, record.project_id, record.connection_id,
                 record.scope, record.version, record.state.value, record.schema_hash,
                 json.dumps(serialization.record_to_dict(record))))
            connection.commit()
        return record.context_id

    def _get(self, ctx: RequestContext, context_id: str) -> ContextRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT record_json FROM context_records WHERE context_id = ? AND org_id = ?",
                (context_id, ctx.organization_id)).fetchone()
        return _decode_record(row) if row else None

    def _find(self, ctx: RequestContext, *, connection_id: str, scope: str | None,
              state: LifecycleState | None) -> list[ContextRecord]:
        query = "SELECT record_json FROM context_records WHERE org_id = ? AND connection_id = ?"
        params: list = [ctx.organization_id, connection_id]
        if scope is not None:
            query += " AND scope = ?"
            params.append(scope)
        if state is not None:
            query += " AND state = ?"
            params.append(state.value)
        query += " ORDER BY version DESC"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_decode_record(row) for row in rows]

    def _active(self, ctx: RequestContext, *, connection_id: str,
                scope: str) -> ContextRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT record_json FROM context_records WHERE org_id = ? AND connection_id = ?"
                " AND scope = ? AND state = ? ORDER BY version DESC LIMIT 1",
                (ctx.organization_id, connection_id, scope,
                 LifecycleState.ACTIVE.value)).fetchone()
        return _decode_record(row) if row else None

    def _set_state(self, ctx: RequestContext, context_id: str, state: LifecycleState,
                   reason: str) -> None:
        record = self._get(ctx, context_id)
        if record is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Context '{context_id}' not found")
        lifecycle.assert_transition(record.state, state)
        updated = _replace(record, state=state, updated_at=_now())
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE context_records SET state = ?, record_json = ? WHERE context_id = ?"
                " AND org_id = ?",
                (state.value, json.dumps(serialization.record_to_dict(updated)),
                 context_id, ctx.organization_id))
            connection.commit()

    def _invalidate(self, ctx: RequestContext, *, connection_id: str, reason: str) -> int:
        marked = 0
        for record in self._find(ctx, connection_id=connection_id, scope=None, state=None):
            if record.state is LifecycleState.SUPERSEDED or record.state is LifecycleState.STALE:
                continue
            if not lifecycle.is_transition_allowed(record.state, LifecycleState.STALE):
                continue
            updated = _replace(record, state=LifecycleState.STALE, updated_at=_now(),
                               notes=reason[:200] or record.notes)
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE context_records SET state = ?, record_json = ?"
                    " WHERE context_id = ? AND org_id = ?",
                    (LifecycleState.STALE.value,
                     json.dumps(serialization.record_to_dict(updated)),
                     record.context_id, ctx.organization_id))
                connection.commit()
            marked += 1
        return marked

    def _versions(self, ctx: RequestContext, *, connection_id: str,
                  scope: str) -> list[ContextRecord]:
        return self._find(ctx, connection_id=connection_id, scope=scope, state=None)

    async def register(self, ctx: RequestContext, record: ContextRecord) -> str:
        return await asyncio.to_thread(self._register, ctx, record)

    async def get(self, ctx: RequestContext, context_id: str) -> ContextRecord | None:
        return await asyncio.to_thread(self._get, ctx, context_id)

    async def find(self, ctx: RequestContext, *, connection_id: str,
                   scope: str | None = None,
                   state: LifecycleState | None = None) -> list[ContextRecord]:
        return await asyncio.to_thread(self._find, ctx, connection_id=connection_id,
                                       scope=scope, state=state)

    async def active(self, ctx: RequestContext, *, connection_id: str,
                     scope: str) -> ContextRecord | None:
        return await asyncio.to_thread(self._active, ctx, connection_id=connection_id,
                                       scope=scope)

    async def set_state(self, ctx: RequestContext, context_id: str,
                        state: LifecycleState, reason: str = "") -> None:
        await asyncio.to_thread(self._set_state, ctx, context_id, state, reason)

    async def invalidate(self, ctx: RequestContext, *, connection_id: str,
                         reason: str) -> int:
        return await asyncio.to_thread(self._invalidate, ctx, connection_id=connection_id,
                                       reason=reason)

    async def versions(self, ctx: RequestContext, *, connection_id: str,
                       scope: str) -> list[ContextRecord]:
        return await asyncio.to_thread(self._versions, ctx, connection_id=connection_id,
                                       scope=scope)


class SqliteContextStore(_SqliteBase):
    def _owns_record(self, connection: sqlite3.Connection, ctx: RequestContext,
                     context_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM context_records WHERE context_id = ? AND org_id = ?",
            (context_id, ctx.organization_id)).fetchone()
        return row is not None

    def _put(self, ctx: RequestContext, context_id: str, artifact: ContextArtifact) -> None:
        with closing(self._connect()) as connection:
            if not self._owns_record(connection, ctx, context_id):
                raise DatahekError(ErrorCode.NOT_FOUND,
                                   f"Context '{context_id}' not found")
            connection.execute(
                "INSERT OR REPLACE INTO context_artifacts"
                " (context_id, kind, org_id, payload_json) VALUES (?, ?, ?, ?)",
                (context_id, artifact.envelope.kind.value, ctx.organization_id,
                 json.dumps(serialization.artifact_to_dict(artifact))))
            connection.commit()

    def _get(self, ctx: RequestContext, context_id: str,
             kind: ArtifactKind) -> ContextArtifact | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM context_artifacts WHERE context_id = ?"
                " AND kind = ? AND org_id = ?",
                (context_id, kind.value, ctx.organization_id)).fetchone()
        if row is None:
            return None
        return serialization.artifact_from_dict(kind, json.loads(row["payload_json"]))

    def _put_package(self, ctx: RequestContext, context_id: str,
                     package: ContextPackage) -> None:
        with closing(self._connect()) as connection:
            if not self._owns_record(connection, ctx, context_id):
                raise DatahekError(ErrorCode.NOT_FOUND,
                                   f"Context '{context_id}' not found")
            connection.execute(
                "INSERT OR REPLACE INTO context_packages (context_id, org_id, payload_json)"
                " VALUES (?, ?, ?)",
                (context_id, ctx.organization_id,
                 json.dumps(serialization.package_to_dict(package))))
            connection.commit()

    def _get_package(self, ctx: RequestContext, context_id: str) -> ContextPackage | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM context_packages WHERE context_id = ?"
                " AND org_id = ?",
                (context_id, ctx.organization_id)).fetchone()
        if row is None:
            return None
        return serialization.package_from_dict(json.loads(row["payload_json"]))

    async def put(self, ctx: RequestContext, context_id: str,
                  artifact: ContextArtifact) -> None:
        await asyncio.to_thread(self._put, ctx, context_id, artifact)

    async def get(self, ctx: RequestContext, context_id: str,
                  kind: ArtifactKind) -> ContextArtifact | None:
        return await asyncio.to_thread(self._get, ctx, context_id, kind)

    async def put_package(self, ctx: RequestContext, context_id: str,
                          package: ContextPackage) -> None:
        await asyncio.to_thread(self._put_package, ctx, context_id, package)

    async def get_package(self, ctx: RequestContext,
                          context_id: str) -> ContextPackage | None:
        return await asyncio.to_thread(self._get_package, ctx, context_id)


def _replace(record: ContextRecord, **changes) -> ContextRecord:
    import dataclasses

    return dataclasses.replace(record, **changes)
