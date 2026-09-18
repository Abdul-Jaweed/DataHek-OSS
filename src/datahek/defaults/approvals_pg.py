"""PostgresApprovalService — durable approvals in the shared PostgreSQL store."""
from datahek.contracts.misc import ApprovalRequest, ApprovalService
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_COLUMNS = "id, org_id, project_id, resource_ref, requester, reason, status, decided_by, created_at"


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "org_id": row[1], "project_id": row[2],
        "resource_ref": row[3], "requester": row[4], "reason": row[5],
        "status": row[6], "decided_by": row[7],
        "created_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
    }


class PostgresApprovalService(ApprovalService):
    def __init__(self, pg: PgMetadata) -> None:
        self._pg = pg

    async def request_approval(self, ctx: object, request: ApprovalRequest) -> str:
        conn = await self._pg.connect()
        try:
            conn.execute(
                "INSERT INTO approvals (id, org_id, project_id, resource_ref, requester, reason, "
                "status) VALUES (%s, %s, %s, %s, %s, %s, 'pending')",
                (request.id, request.org_id, request.project_id, request.resource_ref,
                 request.requester, request.reason))
        finally:
            conn.close()
        return request.id

    async def _get_row(self, approval_id: str):
        conn = await self._pg.connect()
        try:
            cur = conn.execute(f"SELECT {_COLUMNS} FROM approvals WHERE id = %s", (approval_id,))
            return cur.fetchone()
        finally:
            conn.close()

    async def decide(self, approval_id: str, decision: str, actor: str) -> None:
        if decision not in ("approved", "rejected"):
            raise DatahekError(ErrorCode.VALIDATION, "decision must be 'approved' or 'rejected'")
        if await self._get_row(approval_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        conn = await self._pg.connect()
        try:
            conn.execute("UPDATE approvals SET status = %s, decided_by = %s WHERE id = %s",
                         (decision, actor, approval_id))
        finally:
            conn.close()

    async def status(self, approval_id: str) -> str:
        row = await self._get_row(approval_id)
        if row is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        return row[6]

    async def consume(self, approval_id: str) -> None:
        row = await self._get_row(approval_id)
        if row is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        if row[6] == "approved":
            conn = await self._pg.connect()
            try:
                conn.execute("UPDATE approvals SET status = 'consumed' WHERE id = %s",
                             (approval_id,))
            finally:
                conn.close()

    async def list_all(self) -> list[dict]:
        conn = await self._pg.connect()
        try:
            cur = conn.execute(f"SELECT {_COLUMNS} FROM approvals ORDER BY created_at DESC")
            rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_dict(r) for r in rows]
