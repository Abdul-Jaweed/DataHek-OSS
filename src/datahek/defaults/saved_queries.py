"""SqliteSavedQueryStore — saved queries and schedules in the local database."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from datahek.contracts.saved import SavedQuery, SavedQueryStore, Schedule

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_queries (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  question TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  saved_query_id TEXT NOT NULL,
  interval_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  last_status TEXT,
  last_rows INTEGER,
  last_detail TEXT,
  next_run_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run_at);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteSavedQueryStore(SavedQueryStore):
    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("DATAHEK_DB_PATH", "datahek.db")
        conn = sqlite3.connect(self._path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    # ── saved queries ──
    async def create(self, ctx, query: SavedQuery) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO saved_queries (id, org_id, project_id, name, question, "
                "connection_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (query.id, query.org_id, query.project_id, query.name, query.question,
                 query.connection_id, _now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _query_row(row) -> dict:
        return {"id": row[0], "name": row[1], "question": row[2],
                "connection_id": row[3], "created_at": row[4]}

    async def get(self, ctx, query_id: str) -> dict | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, name, question, connection_id, created_at FROM saved_queries "
                "WHERE id = ? AND org_id = ?", (query_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return self._query_row(row) if row else None

    async def list_queries(self, ctx) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, name, question, connection_id, created_at FROM saved_queries "
                "WHERE org_id = ? ORDER BY created_at DESC", (ctx.organization_id,))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._query_row(r) for r in rows]

    async def delete(self, ctx, query_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM saved_queries WHERE id = ? AND org_id = ?",
                         (query_id, ctx.organization_id))
            conn.execute("DELETE FROM schedules WHERE saved_query_id = ?", (query_id,))
            conn.commit()
        finally:
            conn.close()

    # ── schedules ──
    @staticmethod
    def _schedule_row(row) -> dict:
        return {"id": row[0], "saved_query_id": row[1], "interval_seconds": row[2],
                "enabled": bool(row[3]), "last_run_at": row[4], "last_status": row[5],
                "last_rows": row[6], "last_detail": row[7], "next_run_at": row[8]}

    _SCHEDULE_COLS = ("id, saved_query_id, interval_seconds, enabled, last_run_at, "
                      "last_status, last_rows, last_detail, next_run_at")

    async def create_schedule(self, ctx, schedule: Schedule) -> None:
        next_run = (_now() + timedelta(seconds=schedule.interval_seconds)).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO schedules (id, org_id, project_id, saved_query_id, "
                "interval_seconds, enabled, next_run_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (schedule.id, schedule.org_id, schedule.project_id, schedule.saved_query_id,
                 schedule.interval_seconds, 1 if schedule.enabled else 0, next_run, _now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    async def get_schedule(self, ctx, schedule_id: str) -> dict | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                f"SELECT {self._SCHEDULE_COLS} FROM schedules WHERE id = ? AND org_id = ?",
                (schedule_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return self._schedule_row(row) if row else None

    async def list_schedules(self, ctx) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(
                f"SELECT {self._SCHEDULE_COLS} FROM schedules WHERE org_id = ? "
                "ORDER BY created_at DESC", (ctx.organization_id,))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._schedule_row(r) for r in rows]

    async def delete_schedule(self, ctx, schedule_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM schedules WHERE id = ? AND org_id = ?",
                         (schedule_id, ctx.organization_id))
            conn.commit()
        finally:
            conn.close()

    async def due_schedules(self, ctx, now_iso: str) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(
                f"SELECT {self._SCHEDULE_COLS} FROM schedules "
                "WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now_iso,))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._schedule_row(r) for r in rows]

    async def mark_schedule_run(self, ctx, schedule_id: str, status: str,
                                rows: int | None, detail: str, next_run_iso: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, last_status = ?, last_rows = ?, "
                "last_detail = ?, next_run_at = ? WHERE id = ?",
                (_now().isoformat(), status, rows, detail[:500], next_run_iso, schedule_id))
            conn.commit()
        finally:
            conn.close()
