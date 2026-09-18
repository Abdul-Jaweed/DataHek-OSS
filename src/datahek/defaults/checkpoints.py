"""SqliteCheckpointStore — durable per-run checkpoints for inspection & replay.

Stored alongside the conversation database (DATAHEK_DB_PATH).
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from datahek.contracts.misc import CheckpointStore
from datahek.kernel.context import RequestContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  conversation_id TEXT,
  question TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  sql TEXT,
  row_count INTEGER,
  decision TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_org ON checkpoints(org_id, created_at DESC);
"""


class SqliteCheckpointStore(CheckpointStore):
    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("DATAHEK_DB_PATH", "datahek.db")
        conn = sqlite3.connect(self._path)
        try:
            conn.executescript(_SCHEMA)
            try:  # migrate existing databases
                conn.execute("ALTER TABLE checkpoints ADD COLUMN forked_from TEXT")
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    async def save(self, ctx: RequestContext, checkpoint: dict) -> str:
        cid = checkpoint.get("id") or f"cp_{uuid.uuid4().hex[:16]}"
        row = (
            cid, ctx.organization_id, checkpoint.get("conversation_id"),
            checkpoint.get("question", ""), checkpoint.get("connection_id", ""),
            json.dumps(checkpoint.get("plan") or {}), checkpoint.get("sql"),
            checkpoint.get("row_count"), checkpoint.get("decision", "ALLOW"),
            datetime.now(timezone.utc).isoformat(), checkpoint.get("forked_from"),
        )
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (id, org_id, conversation_id, question, "
                "connection_id, plan_json, sql, row_count, decision, created_at, forked_from) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            conn.commit()
        finally:
            conn.close()
        return cid

    @staticmethod
    def _to_dict(row: tuple) -> dict:
        return {
            "id": row[0], "conversation_id": row[1], "question": row[2],
            "connection_id": row[3], "plan": json.loads(row[4]), "sql": row[5],
            "row_count": row[6], "decision": row[7], "created_at": row[8],
            "forked_from": row[9] if len(row) > 9 else None,
        }

    async def get(self, ctx: RequestContext, checkpoint_id: str) -> dict | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, conversation_id, question, connection_id, plan_json, sql, "
                "row_count, decision, created_at, forked_from FROM checkpoints WHERE id = ? AND org_id = ?",
                (checkpoint_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return self._to_dict(row) if row else None

    async def list(self, ctx: RequestContext, limit: int = 20) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, conversation_id, question, connection_id, plan_json, sql, "
                "row_count, decision, created_at, forked_from FROM checkpoints "
                "WHERE org_id = ? ORDER BY created_at DESC LIMIT ?",
                (ctx.organization_id, limit))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._to_dict(r) for r in rows]
