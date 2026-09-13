"""LocalApprovalService — OSS default: in-memory human-in-the-loop approvals.

Enterprise replaces this with a durable, tenant-aware approval workflow.
"""
from datahek.contracts.misc import ApprovalRequest, ApprovalService
from datahek.kernel.errors import DatahekError, ErrorCode


class LocalApprovalService(ApprovalService):
    def __init__(self) -> None:
        self._requests: dict[str, dict] = {}

    async def request_approval(self, ctx: object, request: ApprovalRequest) -> str:
        self._requests[request.id] = {
            "id": request.id,
            "org_id": request.org_id,
            "project_id": request.project_id,
            "resource_ref": request.resource_ref,
            "requester": request.requester,
            "reason": request.reason,
            "status": "pending",
            "decided_by": None,
        }
        return request.id

    async def decide(self, approval_id: str, decision: str, actor: str) -> None:
        entry = self._requests.get(approval_id)
        if entry is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        if decision not in ("approved", "rejected"):
            raise DatahekError(ErrorCode.VALIDATION, "decision must be 'approved' or 'rejected'")
        entry["status"] = decision
        entry["decided_by"] = actor

    async def status(self, approval_id: str) -> str:
        entry = self._requests.get(approval_id)
        if entry is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        return entry["status"]

    async def consume(self, approval_id: str) -> None:
        entry = self._requests.get(approval_id)
        if entry is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found",
                               details={"approval_id": approval_id})
        if entry["status"] == "approved":
            entry["status"] = "consumed"

    def list_all(self) -> list[dict]:
        return list(self._requests.values())
