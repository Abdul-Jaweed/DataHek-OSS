"""SqliteApprovalService — human-in-the-loop approvals that survive restarts.

Same contract as LocalApprovalService, persisted in the local SQLite database
(DATAHEK_DB_PATH) so pending decisions are not lost when the process restarts.
"""
import os
import sqlite3
from datetime import datetime, timezone

from datahek.contracts.misc import ApprovalRequest, ApprovalService
from datahek.kernel.errors import DatahekError, ErrorCode

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  resource_ref TEXT NOT NULL,
  requester TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT,
  created_at TEXT NOT NULL
);
"""


class SqliteApprovalService(ApprovalService):
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
            "id": row[0], "org_id": row[1], "project_id": row[2],
            "resource_ref": row[3], "requester": row[4], "reason": row[5],
            "status": row[6], "decided_by": row[7], "created_at": row[8],
        }

    _SELECT = ("SELECT id, org_id, project_id, resource_ref, requester, reason, "
               "status, decided_by, created_at FROM approvals")

    async def request_approval(self, ctx: object, request: ApprovalRequest) -> str:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO approvals (id, org_id, project_id, resource_ref, "
                "requester, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (request.id, request.org_id, request.project_id, request.resource_ref,
                 request.requester, request.reason, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()
        return request.id

    def _get_row(self, approval_id: str) -> tuple | None:
        conn = self._connect()
        try:
            cur = conn.execute(f"{self._SELECT} WHERE id = ?", (approval_id,))
            return cur.fetchone()
        finally:
            conn.close()

    async def decide(self, approval_id: str, decision: str, actor: str) -> None:
        if decision not in ("approved", "rejected"):
            raise DatahekError(ErrorCode.VALIDATION, "decision must be 'approved' or 'rejected'")
        if self._get_row(approval_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        conn = self._connect()
        try:
            conn.execute("UPDATE approvals SET status = ?, decided_by = ? WHERE id = ?",
                         (decision, actor, approval_id))
            conn.commit()
        finally:
            conn.close()

    async def status(self, approval_id: str) -> str:
        row = self._get_row(approval_id)
        if row is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        return row[6]

    async def consume(self, approval_id: str) -> None:
        row = self._get_row(approval_id)
        if row is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        if row[6] == "approved":
            conn = self._connect()
            try:
                conn.execute("UPDATE approvals SET status = 'consumed' WHERE id = ?",
                             (approval_id,))
                conn.commit()
            finally:
                conn.close()

    def list_all(self) -> list[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(f"{self._SELECT} ORDER BY created_at DESC")
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._row_to_dict(r) for r in rows]
