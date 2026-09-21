"""PostgresConnectionManager — persistent connection catalog with encryption at rest."""
import os
import unittest

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL") or "postgresql://datahek:datahek@127.0.0.1:55432/datahek"
TEST_ORG = "pgtest"


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL"), "postgres test container not running")
class TestPostgresConnectionManager(unittest.TestCase):
    def setUp(self):
        """Isolate tests from rows left by earlier runs (shared test database)."""
        import asyncio
        from datahek.defaults.pg import PgMetadata

        async def clean():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            conn = await pg.connect()
            try:
                conn.execute("DELETE FROM connections WHERE org_id = %s", (TEST_ORG,))
            finally:
                conn.close()

        asyncio.run(clean())

    def test_add_get_list_remove(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="c1", name="ch1", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            got = await mgr.get_connection(ctx, "c1")
            self.assertEqual(got.settings["password"], "s3cret")
            self.assertEqual(len(await mgr.list_connections(ctx)), 1)
            await mgr.remove(ctx, "c1")
            self.assertEqual(len(await mgr.list_connections(ctx)), 0)
            await pg.close()

        asyncio.run(run())

    def test_duplicate_name_rejected(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext
        from datahek.kernel.errors import DatahekError, ErrorCode

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="dup1", name="dup-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            try:
                dup = Connection(id="dup2", name="dup-name", provider="clickhouse",
                                 org_id=TEST_ORG, project_id="default",
                                 settings={"password": "other"})
                with self.assertRaises(DatahekError) as cm:
                    await mgr.add(ctx, dup)
                self.assertEqual(cm.exception.code, ErrorCode.CONNECTION_EXISTS)
            finally:
                await mgr.remove(ctx, "dup1")
                await pg.close()

        asyncio.run(run())

    def test_get_connection_not_found_and_forbidden(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext
        from datahek.kernel.errors import DatahekError, ErrorCode

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            other_ctx = RequestContext(source="api", organization_id="other-org")
            conn = Connection(id="nf1", name="nf-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            try:
                with self.assertRaises(DatahekError) as cm:
                    await mgr.get_connection(ctx, "missing-id")
                self.assertEqual(cm.exception.code, ErrorCode.CONNECTION_NOT_FOUND)
                with self.assertRaises(DatahekError) as cm:
                    await mgr.get_connection(other_ctx, "nf1")
                self.assertEqual(cm.exception.code, ErrorCode.FORBIDDEN)
                with self.assertRaises(DatahekError) as cm:
                    await mgr.remove(other_ctx, "nf1")
                self.assertEqual(cm.exception.code, ErrorCode.FORBIDDEN)
                self.assertEqual(len(await mgr.list_connections(other_ctx)), 0)
            finally:
                await mgr.remove(ctx, "nf1")
                await pg.close()

        asyncio.run(run())

    def test_settings_encrypted_at_rest(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="enc1", name="enc-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret", "user": "readonly"})
            await mgr.add(ctx, conn)
            try:
                raw = await pg.connect()
                try:
                    row = raw.execute(
                        "SELECT settings_json FROM connections WHERE id = %s", ("enc1",)
                    ).fetchone()
                finally:
                    raw.close()
                self.assertIsNotNone(row)
                settings_json = row[0]
                self.assertNotIn("s3cret", settings_json)
                self.assertNotIn("readonly", settings_json)
                self.assertNotIn("enc-name", settings_json)
                got = await mgr.get_connection(ctx, "enc1")
                self.assertEqual(got.settings["password"], "s3cret")
            finally:
                await mgr.remove(ctx, "enc1")
                await pg.close()

        asyncio.run(run())

    def test_plain_settings_when_no_encryption_key(self):
        import asyncio
        import json
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key=None)
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="plain1", name="plain-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            try:
                raw = await pg.connect()
                try:
                    row = raw.execute(
                        "SELECT settings_json FROM connections WHERE id = %s", ("plain1",)
                    ).fetchone()
                finally:
                    raw.close()
                self.assertEqual(json.loads(row[0])["password"], "s3cret")
                got = await mgr.get_connection(ctx, "plain1")
                self.assertEqual(got.settings["password"], "s3cret")
            finally:
                await mgr.remove(ctx, "plain1")
                await pg.close()

        asyncio.run(run())

    def test_secret_ref_stored_as_is(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="sref1", name="sref-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "secret://infisical/prod/datahek/CH_PW"})
            await mgr.add(ctx, conn)
            try:
                got = await mgr.get_connection(ctx, "sref1")
                self.assertEqual(got.settings["password"], "secret://infisical/prod/datahek/CH_PW")
            finally:
                await mgr.remove(ctx, "sref1")
                await pg.close()

        asyncio.run(run())

    def test_secret_ref_round_trip(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.contracts.secrets import SecretRef
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="sref2", name="sref2-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              secret_ref=SecretRef(provider="infisical", name="pg_password"),
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            try:
                got = await mgr.get_connection(ctx, "sref2")
                self.assertEqual(got.secret_ref, SecretRef(provider="infisical", name="pg_password"))
                listed = [c for c in await mgr.list_connections(ctx) if c.id == "sref2"]
                self.assertEqual(len(listed), 1)
                self.assertEqual(listed[0].secret_ref, SecretRef(provider="infisical", name="pg_password"))
            finally:
                await mgr.remove(ctx, "sref2")
                await pg.close()

        asyncio.run(run())

    def test_secret_ref_absent_stays_none(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api", organization_id=TEST_ORG)
            conn = Connection(id="noref1", name="noref-name", provider="clickhouse",
                              org_id=TEST_ORG, project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            try:
                got = await mgr.get_connection(ctx, "noref1")
                self.assertIsNone(got.secret_ref)
            finally:
                await mgr.remove(ctx, "noref1")
                await pg.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
