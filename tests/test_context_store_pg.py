"""PostgreSQL context registry/store — runs against a live server when configured."""
import asyncio
import os
import unittest

from datahek.context.registry import ContextRegistryService
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    FreshnessReport,
    LifecycleState,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TrustLevel,
    ValidationStatus,
)
from datahek.defaults.context_store_pg import PostgresContextRegistry, PostgresContextStore
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL")


def _schema(hash_value="pg-h1"):
    envelope = ArtifactEnvelope(
        kind=ArtifactKind.SCHEMA, schema_version=1, provenance=ProvenanceSource.DATABASE,
        trust=TrustLevel.STRUCTURAL, validation=ValidationStatus.NOT_REQUIRED,
        confidence=1.0, generated_at="2026-09-21T00:00:00Z")
    return SchemaContext(
        envelope=envelope, database="d", schema="public",
        tables=(TableSchema(name="orders", columns=(
            ColumnSchema(name="id", data_type="integer", nullable=False, ordinal=0),)),),
        schema_hash=hash_value)


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=1.0, semantic_confidence=0.0,
                         relationship_coverage=0.0, granularity_confidence=0.0,
                         human_validation=1.0, freshness_score=1.0,
                         governance_coverage=0.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


@unittest.skipUnless(PG_URL, "DATAHEK_TEST_PG_URL not set")
class TestPostgresContextStore(unittest.TestCase):
    def setUp(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.pg = PgMetadata(url=PG_URL)
        self.call(self.pg.init_schema())
        self.registry = PostgresContextRegistry(self.pg)
        self.store = PostgresContextStore(self.pg)
        self.service = ContextRegistryService(self.registry, self.store)
        self.ctx = RequestContext(source="cli", organization_id="pgtest")
        self.call(self._cleanup())

    def tearDown(self):
        self.call(self._cleanup())
        self._loop.close()
        asyncio.set_event_loop(None)

    def call(self, coro):
        return self._loop.run_until_complete(coro)

    async def _cleanup(self):
        connection = await self.pg.connect()
        try:
            connection.execute(
                "DELETE FROM context_artifacts WHERE org_id IN (%s, %s)",
                (self.ctx.organization_id, "other"))
            connection.execute(
                "DELETE FROM context_packages WHERE org_id IN (%s, %s)",
                (self.ctx.organization_id, "other"))
            connection.execute(
                "DELETE FROM context_records WHERE org_id IN (%s, %s)",
                (self.ctx.organization_id, "other"))
        finally:
            connection.close()

    def publish(self, *, schema_hash="pg-h1", skip_if_current=False):
        return self.call(self.service.publish(
            self.ctx, connection_id="pg-conn", scope="connection", schema_hash=schema_hash,
            artifacts={ArtifactKind.SCHEMA: _schema(schema_hash)},
            quality=_quality(), freshness=_freshness()))

    def test_publish_and_read_back(self):
        record = self.publish()
        self.assertEqual(record.version, 1)
        active = self.call(self.registry.active(self.ctx, connection_id="pg-conn",
                                                scope="connection"))
        self.assertEqual(active.context_id, record.context_id)
        stored = self.call(self.store.get(self.ctx, record.context_id, ArtifactKind.SCHEMA))
        self.assertEqual(stored, _schema("pg-h1"))

    def test_versioning_and_supersede(self):
        first = self.publish()
        second = self.publish(schema_hash="pg-h2")
        self.assertEqual(second.version, 2)
        self.assertEqual(
            self.call(self.registry.get(self.ctx, first.context_id)).state,
            LifecycleState.SUPERSEDED)

    def test_tenant_isolation(self):
        record = self.publish()
        other = RequestContext(source="cli", organization_id="other")
        self.assertIsNone(self.call(self.registry.get(other, record.context_id)))
        self.assertIsNone(self.call(
            self.store.get(other, record.context_id, ArtifactKind.SCHEMA)))

    def test_is_current_and_invalidate(self):
        self.publish()
        self.assertTrue(self.call(self.service.is_current(
            self.ctx, connection_id="pg-conn", scope="connection", schema_hash="pg-h1")))
        marked = self.call(self.service.invalidate(self.ctx, connection_id="pg-conn",
                                                   reason="schema changed"))
        self.assertEqual(marked, 1)
        self.assertIsNone(self.call(self.registry.active(self.ctx, connection_id="pg-conn",
                                                         scope="connection")))


if __name__ == "__main__":
    unittest.main()
