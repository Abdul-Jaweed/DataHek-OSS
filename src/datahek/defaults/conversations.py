"""SqliteConversationStore — OSS default: tenant-scoped, persistent conversations.

Zero-dependency (stdlib sqlite3). Enterprise replaces via the
ConversationStore contract (PostgreSQL, RLS).
"""
import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from datahek.kernel.context import RequestContext
from datahek.kernel.ids import new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    title TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT,
    message_type TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON conversations(org_id, project_id);
"""


class SqliteConversationStore:
    def __init__(self, path: Path | str = "datahek.db"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── sync core (runs in worker threads) ──

    def _create(self, ctx: RequestContext, conversation_id: str, title: str | None) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO conversations (id, org_id, project_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, ctx.organization_id, ctx.project_id, title, _now(), _now()),
            )

    def _get(self, ctx: RequestContext, conversation_id: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND org_id = ?",
                (conversation_id, ctx.organization_id),
            ).fetchone()
            if row is None:
                return None
            msgs = conn.execute(
                "SELECT role, content, message_type, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
            return {
                "id": row["id"],
                "org_id": row["org_id"],
                "project_id": row["project_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "messages": [dict(m) for m in msgs],
            }

    def _append(self, ctx: RequestContext, conversation_id: str, message: dict) -> None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT org_id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Conversation '{conversation_id}' not found")
            if row["org_id"] != ctx.organization_id:
                raise PermissionError("Conversation not accessible in this tenant")
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, message_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), conversation_id, message["role"], message.get("content"),
                 message.get("message_type", "text"), _now()),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id)
            )

    def _list(self, ctx: RequestContext, project_id: str, cursor: str | None, limit: int) -> dict:
        with self._session() as conn:
            params: list = [ctx.organization_id, project_id]
            where = "org_id = ? AND project_id = ?"
            if cursor:
                where += " AND id > ?"
                params.append(cursor)
            rows = conn.execute(
                f"SELECT id, title, updated_at FROM conversations WHERE {where} "
                f"ORDER BY id LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        items = [dict(r) for r in rows[:limit]]
        next_cursor = rows[limit]["id"] if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    # ── async API ──

    async def create(self, ctx: RequestContext, conversation_id: str, title: str | None = None) -> None:
        await asyncio.to_thread(self._create, ctx, conversation_id, title)

    async def get(self, ctx: RequestContext, conversation_id: str) -> dict | None:
        return await asyncio.to_thread(self._get, ctx, conversation_id)

    async def append_message(self, ctx: RequestContext, conversation_id: str, message: dict) -> None:
        await asyncio.to_thread(self._append, ctx, conversation_id, message)

    async def list_by_project(self, ctx: RequestContext, project_id: str,
                              cursor: str | None = None, limit: int = 50) -> dict:
        return await asyncio.to_thread(self._list, ctx, project_id, cursor, limit)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()