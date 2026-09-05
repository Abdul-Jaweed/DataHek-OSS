"""Usage metering, approvals, entitlement, storage, and observability contracts."""
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from datahek.kernel.context import RequestContext


# ── Usage ──

@dataclass(frozen=True)
class UsageEvent:
    meter: str
    org_id: str
    project_id: str
    amount: float = 1.0
    payload: dict = field(default_factory=dict)


@runtime_checkable
class UsageMeter(Protocol):
    async def record(self, event: UsageEvent) -> None: ...
    async def current_usage(self, ctx: RequestContext, meter: str) -> float: ...


# ── Approvals ──

@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    org_id: str
    project_id: str
    resource_ref: str
    requester: str
    reason: str = ""


@runtime_checkable
class ApprovalService(Protocol):
    async def request_approval(self, ctx: RequestContext, request: ApprovalRequest) -> str: ...
    async def decide(self, approval_id: str, decision: str, actor: str) -> None: ...
    async def status(self, approval_id: str) -> str: ...


# ── Entitlements (contract) ──

@runtime_checkable
class EntitlementService(Protocol):
    async def check(self, ctx: RequestContext, capability: str) -> bool: ...
    async def limits(self, ctx: RequestContext, resource: str) -> dict[str, int]: ...


# ── Storage ──

@runtime_checkable
class ConversationStore(Protocol):
    async def create(self, ctx: RequestContext, conversation_id: str, title: str | None = None) -> None: ...
    async def get(self, ctx: RequestContext, conversation_id: str) -> dict | None: ...
    async def append_message(self, ctx: RequestContext, conversation_id: str, message: dict) -> None: ...
    async def list_by_project(self, ctx: RequestContext, project_id: str,
                              cursor: str | None = None, limit: int = 50) -> dict: ...


@runtime_checkable
class MetadataStore(Protocol):
    async def get(self, ctx: RequestContext, kind: str, entity_id: str) -> dict | None: ...
    async def put(self, ctx: RequestContext, entity: dict) -> None: ...


@runtime_checkable
class JobStore(Protocol):
    async def enqueue(self, job: dict) -> None: ...
    async def claim(self, worker_id: str, kinds: list[str]) -> dict | None: ...
    async def ack(self, job_id: str) -> None: ...


# ── Observability ──

@runtime_checkable
class Tracer(Protocol):
    def span(self, name: str, **attrs: Any) -> Any: ...