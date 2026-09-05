"""Domain identifiers — sortable, opaque, collision-free.

Format: 16 hex chars of millisecond timestamp + 24 hex chars of uuid4
(total 40 chars). Entity ids carry a typed prefix, e.g. ``conn_``.
"""
import time
import uuid

_PREFIXES = {
    "organization": "org",
    "workspace": "ws",
    "project": "prj",
    "user": "usr",
    "connection": "conn",
    "conversation": "conv",
    "message": "msg",
    "audit": "audit",
    "policy": "pol",
    "request": "req",
    "event": "evt",
}

_last_ts: int = 0


def new_id() -> str:
    """A new time-ordered unique id (strictly sortable by creation time)."""
    global _last_ts
    ts = int(time.time() * 1000)
    if ts <= _last_ts:
        ts = _last_ts + 1
    _last_ts = ts
    return f"{ts:016x}{uuid.uuid4().hex[:24]}"


def entity_id(kind: str) -> str:
    """A typed entity id: ``<prefix>_<new_id>``."""
    prefix = _PREFIXES.get(kind, "ent")
    return f"{prefix}_{new_id()}"