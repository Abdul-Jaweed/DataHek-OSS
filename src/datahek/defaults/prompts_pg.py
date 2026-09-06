"""PostgresPromptStore — opt-in PostgreSQL persistence for prompt templates.

Mirrors SqlitePromptStore semantics (tenant-scoped get/list, scoped update and
delete) while persisting rows in the `prompts` table created by PgMetadata.
The template count limit (3) is enforced by the entitlements layer, not here.
"""
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

_COLUMNS = "id, org_id, project_id, name, content, created_at"


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "org_id": row[1],
        "project_id": row[2],
        "name": row[3],
        "content": row[4],
        "created_at": row[5].isoformat(),
    }


class PostgresPromptStore:
    def __init__(self, pg: PgMetadata | None = None):
        self._pg = pg or PgMetadata()

    async def create(self, ctx: RequestContext, template_id: str, name: str, content: str) -> None:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO prompts (id, org_id, project_id, name, content) "
                "VALUES (%s, %s, %s, %s, %s)",
                (template_id, ctx.organization_id, ctx.project_id, name, content),
            )
        finally:
            conn.close()

    async def get(self, ctx: RequestContext, template_id: str) -> dict | None:
        conn = await self._pg.connect()
        try:
            row = conn.execute(
                "SELECT " + _COLUMNS + " FROM prompts WHERE id = %s AND org_id = %s",
                (template_id, ctx.organization_id),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    async def update(self, ctx: RequestContext, template_id: str, content: str) -> None:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "UPDATE prompts SET content = %s WHERE id = %s AND org_id = %s",
                (content, template_id, ctx.organization_id),
            )
        finally:
            conn.close()

    async def delete(self, ctx: RequestContext, template_id: str) -> None:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "DELETE FROM prompts WHERE id = %s AND org_id = %s",
                (template_id, ctx.organization_id),
            )
        finally:
            conn.close()

    async def list(self, ctx: RequestContext) -> list[dict]:
        conn = await self._pg.connect()
        try:
            rows = conn.execute(
                "SELECT " + _COLUMNS + " FROM prompts "
                "WHERE org_id = %s AND project_id = %s ORDER BY created_at, id",
                (ctx.organization_id, ctx.project_id),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()
