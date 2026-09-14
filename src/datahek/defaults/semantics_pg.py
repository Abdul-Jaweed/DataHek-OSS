"""PostgresSemanticStore — metric definitions in the shared PostgreSQL store."""
from datahek.contracts.semantics import Metric, SemanticStore
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

_COLUMNS = "id, name, table_name, aggregate, column_name, filter, description, created_at"

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
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_metrics_org ON metrics(org_id);
"""


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "name": row[1], "table": row[2], "aggregate": row[3],
        "column": row[4], "filter": row[5], "description": row[6],
        "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
    }


class PostgresSemanticStore(SemanticStore):
    def __init__(self, pg: PgMetadata) -> None:
        self._pg = pg
        self._initialized = False

    async def _ensure(self) -> None:
        if not self._initialized:
            conn = await self._pg.connect()
            try:
                conn.execute(_SCHEMA)
            finally:
                conn.close()
            self._initialized = True

    async def create(self, ctx, metric: Metric) -> None:
        await self._ensure()
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO metrics (id, org_id, project_id, name, table_name, aggregate, "
                "column_name, filter, description) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (metric.id, metric.org_id, metric.project_id, metric.name, metric.table,
                 metric.aggregate, metric.column, metric.filter, metric.description))
        finally:
            conn.close()

    async def get(self, ctx: RequestContext, metric_id: str) -> dict | None:
        await self._ensure()
        conn = await self._pg.connect()
        try:
            cur = conn.execute(
                f"SELECT {_COLUMNS} FROM metrics WHERE id = %s AND org_id = %s",
                (metric_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return _row_to_dict(row) if row else None

    async def update(self, ctx: RequestContext, metric_id: str, patch: dict) -> None:
        current = await self.get(ctx, metric_id)
        if current is None:
            return
        merged = {**current, **patch}
        conn = await self._pg.connect()
        try:
            conn.execute(
                "UPDATE metrics SET name = %s, table_name = %s, aggregate = %s, "
                "column_name = %s, filter = %s, description = %s WHERE id = %s AND org_id = %s",
                (merged["name"], merged["table"], merged["aggregate"], merged["column"],
                 merged["filter"], merged["description"], metric_id, ctx.organization_id))
        finally:
            conn.close()

    async def delete(self, ctx: RequestContext, metric_id: str) -> None:
        await self._ensure()
        conn = await self._pg.connect()
        try:
            conn.execute("DELETE FROM metrics WHERE id = %s AND org_id = %s",
                         (metric_id, ctx.organization_id))
        finally:
            conn.close()

    async def list(self, ctx: RequestContext) -> list[dict]:
        await self._ensure()
        conn = await self._pg.connect()
        try:
            cur = conn.execute(
                f"SELECT {_COLUMNS} FROM metrics WHERE org_id = %s ORDER BY created_at DESC",
                (ctx.organization_id,))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_dict(r) for r in rows]
