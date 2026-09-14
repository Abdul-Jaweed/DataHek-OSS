"""SqliteSemanticStore — metric definitions in the local SQLite database."""
import os
import sqlite3
from datetime import datetime, timezone

from datahek.contracts.semantics import Metric, SemanticStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  table_name TEXT NOT NULL,
  aggregate TEXT NOT NULL,
  column_name TEXT NOT NULL DEFAULT '*',
  filter TEXT,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_org ON metrics(org_id);
"""


class SqliteSemanticStore(SemanticStore):
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

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        return {
            "id": row[0], "name": row[1], "table": row[2], "aggregate": row[3],
            "column": row[4], "filter": row[5], "description": row[6], "created_at": row[7],
        }

    _SELECT = ("SELECT id, name, table_name, aggregate, column_name, filter, description, created_at "
               "FROM metrics")

    async def create(self, ctx, metric: Metric) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO metrics (id, org_id, project_id, name, table_name, aggregate, "
                "column_name, filter, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (metric.id, metric.org_id, metric.project_id, metric.name, metric.table,
                 metric.aggregate, metric.column, metric.filter, metric.description,
                 datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()

    async def get(self, ctx, metric_id: str) -> dict | None:
        conn = self._connect()
        try:
            cur = conn.execute(f"{self._SELECT} WHERE id = ? AND org_id = ?",
                               (metric_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return self._row_to_dict(row) if row else None

    async def update(self, ctx, metric_id: str, patch: dict) -> None:
        current = await self.get(ctx, metric_id)
        if current is None:
            return
        merged = {**current, **patch}
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE metrics SET name = ?, table_name = ?, aggregate = ?, column_name = ?, "
                "filter = ?, description = ? WHERE id = ? AND org_id = ?",
                (merged["name"], merged["table"], merged["aggregate"], merged["column"],
                 merged["filter"], merged["description"], metric_id, ctx.organization_id))
            conn.commit()
        finally:
            conn.close()

    async def delete(self, ctx, metric_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM metrics WHERE id = ? AND org_id = ?",
                         (metric_id, ctx.organization_id))
            conn.commit()
        finally:
            conn.close()

    async def list(self, ctx) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(f"{self._SELECT} WHERE org_id = ? ORDER BY created_at DESC",
                               (ctx.organization_id,))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._row_to_dict(r) for r in rows]
