"""Domain events — the normalized event model for audit, usage, and hooks."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from datahek.kernel import ids


@dataclass
class DomainEvent:
    type: str
    actor: str
    event_id: str = field(default_factory=ids.new_id)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict = field(default_factory=dict)
    tenant: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "tenant": self.tenant,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DomainEvent":
        return cls(
            type=data["type"],
            actor=data["actor"],
            event_id=data.get("event_id", ids.new_id()),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            payload=data.get("payload", {}),
            tenant=data.get("tenant", {}),
        )


class EventStore:
    """In-memory event store (OSS default)."""

    def __init__(self):
        self._events: list[DomainEvent] = []

    def record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def events(self) -> list[DomainEvent]:
        return list(self._events)