"""PostgresConversationStore — opt-in PostgreSQL persistence for conversations.

Mirrors SqliteConversationStore semantics (tenant-scoped get/list, KeyError on
append to unknown conversation, PermissionError across orgs) while persisting
rows in the `conversations` / `messages` tables created by PgMetadata.
Message ids are SERIAL; deleting a conversation cascades its messages via the
DDL's ON DELETE CASCADE.
"""
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

_CONV_COLUMNS = "id, org_id, project_id, title, created_at"
_MSG_COLUMNS = "role, content, message_type, created_at"


class PostgresConversationStore:
    def __init__(self, pg: PgMetadata | None = None):
        self._pg = pg or PgMetadata()

    async def create(self, ctx: RequestContext, conversation_id: str, title: str | None = None) -> None:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO conversations (id, org_id, project_id, title) "
                "VALUES (%s, %s, %s, %s)",
                (conversation_id, ctx.organization_id, ctx.project_id, title),
            )
        finally:
            conn.close()

    async def get(self, ctx: RequestContext, conversation_id: str) -> dict | None:
        conn = await self._pg.connect()
        try:
            row = conn.execute(
                "SELECT " + _CONV_COLUMNS + " FROM conversations WHERE id = %s AND org_id = %s",
                (conversation_id, ctx.organization_id),
            ).fetchone()
            if row is None:
                return None
            msg_rows = conn.execute(
                "SELECT " + _MSG_COLUMNS + " FROM messages "
                "WHERE conversation_id = %s ORDER BY created_at, id",
                (conversation_id,),
            ).fetchall()
            return {
                "id": row[0],
                "org_id": row[1],
                "project_id": row[2],
                "title": row[3],
                "created_at": row[4].isoformat(),
                "messages": [
                    {
                        "role": m[0],
                        "content": m[1],
                        "message_type": m[2],
                        "created_at": m[3].isoformat(),
                    }
                    for m in msg_rows
                ],
            }
        finally:
            conn.close()

    async def append_message(self, ctx: RequestContext, conversation_id: str, message: dict) -> None:
        conn = await self._pg.connect()
        try:
            row = conn.execute(
                "SELECT org_id FROM conversations WHERE id = %s", (conversation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Conversation '{conversation_id}' not found")
            if row[0] != ctx.organization_id:
                raise PermissionError("Conversation not accessible in this tenant")
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, message_type) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (conversation_id, message["role"], message.get("content"),
                 message.get("message_type", "text")),
            )
        finally:
            conn.close()

    async def list_by_project(self, ctx: RequestContext, project_id: str,
                              cursor: str | None = None, limit: int = 50) -> dict:
        conn = await self._pg.connect()
        try:
            params: list = [ctx.organization_id, project_id]
            where = "org_id = %s AND project_id = %s"
            if cursor:
                where += " AND id > %s"
                params.append(cursor)
            rows = conn.execute(
                "SELECT id, title FROM conversations WHERE " + where +
                " ORDER BY id LIMIT %s",
                [*params, limit + 1],
            ).fetchall()
        finally:
            conn.close()
        items = [{"id": r[0], "title": r[1]} for r in rows[:limit]]
        next_cursor = rows[limit][0] if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}
