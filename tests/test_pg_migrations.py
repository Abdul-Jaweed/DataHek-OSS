"""PostgreSQL schema migrations — versioned, ordered, idempotent-safe."""
import unittest

try:
    from datahek.defaults.pg import _MIGRATIONS, pending_migrations

    HAS_PSYCOPG = True
except ImportError:  # optional extra not installed
    HAS_PSYCOPG = False


@unittest.skipUnless(HAS_PSYCOPG, "psycopg not installed")
class TestMigrations(unittest.TestCase):
    def test_versions_are_ordered_and_unique(self):
        versions = [version for version, _ in _MIGRATIONS]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(len(versions), len(set(versions)))
        self.assertEqual(versions[0], 1)

    def test_pending_migrations(self):
        all_versions = [version for version, _ in _MIGRATIONS]
        self.assertEqual(pending_migrations(set()), all_versions)
        self.assertEqual(pending_migrations(set(all_versions)), [])
        if len(all_versions) > 1:
            applied = set(all_versions[:-1])
            self.assertEqual(pending_migrations(applied), all_versions[-1:])


if __name__ == "__main__":
    unittest.main()
