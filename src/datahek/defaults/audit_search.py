"""Audit search — query the JSONL audit trail (tail-read, filtered).

The audit file is append-only; search reads the most recent slice rather than
the whole file, so it stays fast as the trail grows.
"""
import json
import os

_MAX_TAIL_BYTES = 2 * 1024 * 1024  # read the last ~2 MB


def search_audit(path: str | None = None, limit: int = 50,
                 event_type: str | None = None, actor: str | None = None,
                 decision: str | None = None, contains: str | None = None) -> list[dict]:
    """Return newest-first audit events matching the filters."""
    path = path or os.environ.get("DATAHEK_AUDIT_PATH", "datahek-audit.jsonl")
    if not os.path.exists(path) or limit <= 0:
        return []

    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - _MAX_TAIL_BYTES))
        chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.splitlines()
    if size > _MAX_TAIL_BYTES and lines:
        lines = lines[1:]  # drop the partial first line

    results: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_type and event.get("event_type") != event_type:
            continue
        if actor and event.get("actor") != actor:
            continue
        if decision and event.get("decision") != decision:
            continue
        if contains and contains.lower() not in json.dumps(event).lower():
            continue
        results.append(event)
        if len(results) >= limit:
            break
    return results
