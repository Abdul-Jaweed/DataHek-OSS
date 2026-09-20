import os
import unittest

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL")
if not PG_URL:
    PG_URL = "postgresql://datahek:datahek@localhost:5433/datahek"  # docker compose postgres service


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL"), "postgres test container not running")
class TestPgMetadata(unittest.TestCase):
    def test_init_schema_and_roundtrip(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            conn = await pg.connect()
            cur = conn.execute("SELECT to_regclass('public.connections')")
            self.assertIsNotNone(cur.fetchone()[0])
            await pg.close()

        asyncio.run(run())
