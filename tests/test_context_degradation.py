"""Context degradation — /ask never breaks when the Context Layer fails (FR-020)."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    ContextComposer,
    ContextRetriever,
    FreshnessReport,
    GovernanceContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TrustLevel,
    ValidationStatus,
)
from datahek.contracts.models import ModelProvider, ModelRequest, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.context.registry import ContextRegistryService
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

_PLAN = (
    '{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], '
    '"aggregates": [{"function": "count", "column": "*", "alias": "n"}], '
    '"group_by": ["service"], "limit": 10}]}'
)


class _FakeModel(ModelProvider):
    def __init__(self, response: str = _PLAN):
        self._response = response

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content=self._response)

    async def stream(self, request: ModelRequest):
        yield self._response


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="clickhouse",
                                         read_only=ReadOnlyLevel.STRUCTURAL,
                                         max_result_rows=1000)

    async def connect(self, connection: Connection):
        return object()

    async def ping(self, client):
        return {"ok": True}

    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[
                ColumnMeta(name="service", data_type="String"),
                ColumnMeta(name="status", data_type="String"),
            ], row_count=12)])

    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"},
                            {"name": "n", "type": "UInt64"}],
                "rows": [("payment-api", 7)]}

    async def close(self, client):
        pass


class _BoomRetriever:
    async def retrieve(self, *args, **kwargs):
        raise RuntimeError("context store down")


class _TinyComposer:
    async def compose(self, ctx, retrieved, runtime):
        from datahek.context.composer import BudgetContextComposer

        return await BudgetContextComposer().compose(ctx, retrieved, runtime, budget_tokens=1)


def _envelope(kind, provenance=ProvenanceSource.DATABASE, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=ValidationStatus.NOT_REQUIRED, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="traces", columns=(
            ColumnSchema(name="service", data_type="String", nullable=True, ordinal=0),
            ColumnSchema(name="status", data_type="String", nullable=True, ordinal=1)),
            primary_key=()),),
        schema_hash="h1")


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=0.6, semantic_confidence=0.6,
                         relationship_coverage=0.6, granularity_confidence=0.9,
                         human_validation=0.0, freshness_score=1.0,
                         governance_coverage=1.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


def _governance():
    return GovernanceContext(
        envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM, TrustLevel.SYSTEM),
        sensitive_columns=(), restricted_columns=(), allowed_operations=("SELECT",),
        masking_policy_refs=(), permission_version="p1")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATAHEK_DB_PATH"] = str(Path(self._tmp.name) / "datahek.db")
        container = build_app_container()
        container.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        container.override(ProviderRegistry, registry)
        self.connection_id = "c1"
        asyncio.run(container.resolve(ConnectionManager).add(
            RequestContext(source="cli"),
            Connection(id="c1", name="ch1", provider="clickhouse",
                       org_id="default", project_id="default")))
        self.container = container

    def tearDown(self):
        os.environ.pop("DATAHEK_DB_PATH", None)
        self._tmp.cleanup()

    def app(self):
        return TestClient(create_app(self.container))

    def publish(self):
        service = self.container.resolve(ContextRegistryService)
        return asyncio.run(service.publish(
            RequestContext(source="cli"), connection_id=self.connection_id,
            scope="connection", schema_hash="h1",
            artifacts={ArtifactKind.SCHEMA: _schema(),
                       ArtifactKind.GOVERNANCE: _governance()},
            quality=_quality(), freshness=_freshness()))


class TestAskDegradation(_Base):
    def test_ask_survives_retriever_failure(self):
        self.publish()
        self.container.override(ContextRetriever, _BoomRetriever())
        client = self.app()
        resp = client.post("/ask", json={"question": "error count by service",
                                         "connection_id": self.connection_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["plan_sources"], ["traces"])
        self.assertEqual(body["rows"], [{"service": "payment-api", "n": 7}])

    def test_ask_clarifies_on_insufficient_context(self):
        self.publish()
        self.container.override(ContextComposer, _TinyComposer())
        client = self.app()
        resp = client.post("/ask", json={"question": "error count by service",
                                         "connection_id": self.connection_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body.get("sql"))
        self.assertIn("context", body["clarification"].lower())

    def test_ask_without_record_uses_live_catalog(self):
        client = self.app()
        resp = client.post("/ask", json={"question": "error count by service",
                                         "connection_id": self.connection_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_sources"], ["traces"])


if __name__ == "__main__":
    unittest.main()
