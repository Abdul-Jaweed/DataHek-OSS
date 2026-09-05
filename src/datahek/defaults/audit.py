"""JsonlAuditSink — OSS default: append-only JSONL audit trail."""
import json
import os
from pathlib import Path

from datahek.contracts.audit import AuditEvent, AuditSink


class JsonlAuditSink(AuditSink):
    def __init__(self, path: Path | str | None = None):
        self._path = Path(path or os.getenv("DATAHEK_AUDIT_PATH", "datahek-audit.jsonl"))

    async def record(self, event: AuditEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")