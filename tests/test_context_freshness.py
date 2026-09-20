"""Freshness evaluation — per-artifact age, hash match, and permission match."""
import unittest
from datetime import datetime, timedelta, timezone

from datahek.context.freshness import evaluate_freshness

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class TestFreshness(unittest.TestCase):
    def test_event_driven_artifact_is_fresh_without_ttl(self):
        report = evaluate_freshness(generated_at=_iso(NOW - timedelta(days=365)),
                                    artifact_schema_hash="h", now=NOW)
        self.assertEqual(report.state, "fresh")
        self.assertIsNone(report.refresh_due_at)
        self.assertTrue(report.schema_hash_matches)

    def test_young_artifact_is_fresh(self):
        report = evaluate_freshness(generated_at=_iso(NOW - timedelta(hours=1)),
                                    artifact_schema_hash="h", max_age_seconds=24 * 3600,
                                    now=NOW)
        self.assertEqual(report.state, "fresh")
        self.assertEqual(report.age_seconds, 3600)
        self.assertIsNotNone(report.refresh_due_at)

    def test_half_life_is_aging(self):
        report = evaluate_freshness(generated_at=_iso(NOW - timedelta(hours=18)),
                                    artifact_schema_hash="h", max_age_seconds=24 * 3600,
                                    now=NOW)
        self.assertEqual(report.state, "aging")

    def test_expired_is_stale(self):
        report = evaluate_freshness(generated_at=_iso(NOW - timedelta(hours=30)),
                                    artifact_schema_hash="h", max_age_seconds=24 * 3600,
                                    now=NOW)
        self.assertEqual(report.state, "stale")

    def test_schema_hash_mismatch_is_stale(self):
        report = evaluate_freshness(generated_at=_iso(NOW), artifact_schema_hash="old",
                                    current_schema_hash="new", now=NOW)
        self.assertEqual(report.state, "stale")
        self.assertFalse(report.schema_hash_matches)

    def test_permission_change_is_stale(self):
        report = evaluate_freshness(generated_at=_iso(NOW), artifact_schema_hash="h",
                                    permission_version_matches=False, now=NOW)
        self.assertEqual(report.state, "stale")
        self.assertFalse(report.permission_version_matches)

    def test_unparseable_timestamp_is_unknown(self):
        report = evaluate_freshness(generated_at="not-a-timestamp",
                                    artifact_schema_hash="h", now=NOW)
        self.assertEqual(report.state, "unknown")


if __name__ == "__main__":
    unittest.main()
