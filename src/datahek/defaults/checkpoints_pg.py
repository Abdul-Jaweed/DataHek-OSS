"""PostgresCheckpointStore — durable checkpoints in the shared PostgreSQL store."""
from datahek.contracts.misc import CheckpointStore
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext
from datahek.kernel.ids import new_id

_COLUMNS = "id, conversation_id, question, connection_id, plan_json, sql, row_count, decision, created_at"


def _row_to_dict(row) -> dict:
    import json

    return {
        "id": row[0], "conversation_id": row[1], "question": row[2],
        "connection_id": row[3], "plan": json.loads(row[4]), "sql": row[5],
        "row_count": row[6], "decision": row[7],
        "created_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
    }


class PostgresCheckpointStore(CheckpointStore):
    def __init__(self, pg: PgMetadata) -> None:
        self._pg = pg

    async def save(self, ctx: RequestContext, checkpoint: dict) -> str:
        import json

        cid = checkpoint.get("id") or f"cp_{new_id()[:16]}"
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO checkpoints (id, org_id, conversation_id, question, connection_id, "
                "plan_json, sql, row_count, decision) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (cid, ctx.organization_id, checkpoint.get("conversation_id"),
                 checkpoint.get("question", ""), checkpoint.get("connection_id", ""),
                 json.dumps(checkpoint.get("plan") or {}), checkpoint.get("sql"),
                 checkpoint.get("row_count"), checkpoint.get("decision", "ALLOW")))
        finally:
            conn.close()
        return cid

    async def get(self, ctx: RequestContext, checkpoint_id: str) -> dict | None:
        conn = await self._pg.connect()
        try:
            cur = conn.execute(
                f"SELECT {_COLUMNS} FROM checkpoints WHERE id = %s AND org_id = %s",
                (checkpoint_id, ctx.organization_id))
            row = cur.fetchone()
        finally:
            conn.close()
        return _row_to_dict(row) if row else None

    async def list(self, ctx: RequestContext, limit: int = 20) -> list[dict]:
        conn = await self._pg.connect()
        try:
            cur = conn.execute(
                f"SELECT {_COLUMNS} FROM checkpoints WHERE org_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (ctx.organization_id, limit))
            rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_dict(r) for r in rows]
