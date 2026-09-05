"""Audit contract — every decision and action recorded."""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from datahek.kernel import ids


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor: str
    action: str
    resource_ref: str | None = None
    decision: str | None = None
    policy_version: str | None = None
    tenant: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    event_id: str = field(default_factory=ids.new_id)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "action": self.action,
            "resource_ref": self.resource_ref,
            "decision": self.decision,
            "policy_version": self.policy_version,
            "tenant": self.tenant,
            "payload": self.payload,
        }


@runtime_checkable
class AuditSink(Protocol):
    async def record(self, event: AuditEvent) -> None: ...