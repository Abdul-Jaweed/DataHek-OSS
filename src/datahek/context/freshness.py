"""Freshness evaluation — per-artifact age, hash match, and permission match (ADR-009).

Schema-class artifacts are event-driven (no TTL): a matching ``schema_hash`` is
fresh forever. Statistics get a TTL (aging past half-life, stale past the
deadline). Permission mismatches always read stale — governance is never served
out of date.
"""
from datetime import datetime, timedelta, timezone

from datahek.contracts.context import FreshnessReport


def _parse(moment: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate_freshness(*, generated_at: str, artifact_schema_hash: str,
                       current_schema_hash: str | None = None,
                       permission_version_matches: bool = True,
                       max_age_seconds: int | None = None,
                       now: datetime | None = None) -> FreshnessReport:
    reference = now or datetime.now(timezone.utc)
    schema_hash_matches = (current_schema_hash is None
                           or current_schema_hash == artifact_schema_hash)
    generated = _parse(generated_at)
    age_seconds = 0
    refresh_due_at = None
    if generated is not None:
        age_seconds = max(0, int((reference - generated).total_seconds()))
        if max_age_seconds is not None:
            refresh_due_at = (generated + timedelta(seconds=max_age_seconds)).isoformat()

    if not schema_hash_matches or not permission_version_matches:
        state = "stale"
    elif generated is None:
        state = "unknown"
    elif max_age_seconds is None:
        state = "fresh"
    elif age_seconds <= max_age_seconds / 2:
        state = "fresh"
    elif age_seconds <= max_age_seconds:
        state = "aging"
    else:
        state = "stale"

    return FreshnessReport(
        state=state,
        age_seconds=age_seconds,
        schema_hash_matches=schema_hash_matches,
        permission_version_matches=permission_version_matches,
        refresh_due_at=refresh_due_at,
    )
