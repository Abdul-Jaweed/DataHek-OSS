"""PostgresEvaluationStore — opt-in PostgreSQL persistence for evaluation runs.

Mirrors InMemoryEvaluationStore semantics (tenant-scoped record/list/aggregate)
while persisting rows in the `evaluation_runs` table created by PgMetadata.
Run dicts are stored as JSON; `list` returns them newest-first and `aggregate`
matches the in-memory store's shape.
"""
import json

from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext
from datahek.kernel.ids import entity_id


class PostgresEvaluationStore:
    def __init__(self, pg: PgMetadata | None = None):
        self._pg = pg or PgMetadata()

    async def record(self, ctx: RequestContext, run: dict) -> None:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO evaluation_runs (id, org_id, project_id, run_json) "
                "VALUES (%s, %s, %s, %s)",
                (entity_id("eval"), ctx.organization_id, ctx.project_id,
                 json.dumps(run)),
            )
        finally:
            conn.close()

    async def list(self, ctx: RequestContext) -> list[dict]:
        conn = await self._pg.connect()
        try:
            rows = conn.execute(
                "SELECT run_json FROM evaluation_runs "
                "WHERE org_id = %s ORDER BY created_at DESC, id DESC",
                (ctx.organization_id,),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        finally:
            conn.close()

    async def aggregate(self, ctx: RequestContext) -> dict:
        runs = await self.list(ctx)
        total = len(runs)
        passed = sum(1 for r in runs if r["scores"].get("execution", 0) >= 1.0)
        return {"total": total, "passed": passed,
                "pass_rate": (passed / total) if total else 0.0,
                "runs": runs}
