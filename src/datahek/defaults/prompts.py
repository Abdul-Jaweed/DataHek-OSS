"""Prompt templates — OSS: up to 3 custom planner prompts, tenant-scoped.

SQLite-backed; the entitlement layer enforces the template limit.
"""
import asyncio
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from datahek.kernel.context import RequestContext
from datahek.kernel.ids import new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_prompts_tenant ON prompt_templates(org_id, project_id);
"""


def _run(coro):
    return asyncio.run(coro)


class SqlitePromptStore:
    def __init__(self, path: Path | str | None = None):
        self._path = Path(path or os.getenv("DATAHEK_DB_PATH", "datahek.db"))
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

    # ── sync core ──

    def _create(self, ctx: RequestContext, template_id: str, name: str, content: str) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO prompt_templates (id, org_id, project_id, name, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (template_id, ctx.organization_id, ctx.project_id, name, content, _now(), _now()),
            )

    def _get(self, ctx: RequestContext, template_id: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE id = ? AND org_id = ?",
                (template_id, ctx.organization_id),
            ).fetchone()
            return dict(row) if row else None

    def _update(self, ctx: RequestContext, template_id: str, content: str) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE prompt_templates SET content = ?, updated_at = ? WHERE id = ? AND org_id = ?",
                (content, _now(), template_id, ctx.organization_id),
            )

    def _delete(self, ctx: RequestContext, template_id: str) -> None:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM prompt_templates WHERE id = ? AND org_id = ?",
                (template_id, ctx.organization_id),
            )

    def _list(self, ctx: RequestContext) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_templates WHERE org_id = ? AND project_id = ? ORDER BY created_at",
                (ctx.organization_id, ctx.project_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── async API ──

    async def create(self, ctx: RequestContext, template_id: str, name: str, content: str) -> None:
        await asyncio.to_thread(self._create, ctx, template_id, name, content)

    async def get(self, ctx: RequestContext, template_id: str) -> dict | None:
        return await asyncio.to_thread(self._get, ctx, template_id)

    async def update(self, ctx: RequestContext, template_id: str, content: str) -> None:
        await asyncio.to_thread(self._update, ctx, template_id, content)

    async def delete(self, ctx: RequestContext, template_id: str) -> None:
        await asyncio.to_thread(self._delete, ctx, template_id)

    async def list(self, ctx: RequestContext) -> list[dict]:
        return await asyncio.to_thread(self._list, ctx)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()