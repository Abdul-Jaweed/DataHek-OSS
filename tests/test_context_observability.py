"""Context observability — metrics counters and audit events (FR-016)."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ContextRetriever,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    ColumnSchema,
    TrustLevel,
    ValidationStatus,
)
from datahek.contracts.models import ModelProvider, ModelRequest, ModelResponse
from datahek.context.jobs.build_context import BuildResult, ContextBuildJob
from datahek.context.registry import ContextRegistryService
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.kernel.context import RequestContext


class _FakeModel(ModelProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content='{"nodes": []}')

    async def stream(self, request: ModelRequest):
        yield ""


class _FakeProvider:
    provider_id = "sqlite"

    class capabilities:
        dialect = "sqlite"


class _FakeBuildJob(ContextBuildJob):
    def __init__(self):
        super().__init__(schema_service=None, registry_service=None)

    async def run(self, ctx, connection, provider, **kwargs):
        return BuildResult(connection_id=connection.id, state="active",
                           context_id="ctx-built", version=1,
                           quality=_quality(), freshness=_freshness())


class _BoomRetriever:
    async def retrieve(self, *args, **kwargs):
        raise RuntimeError("context store down")


def _envelope(kind, provenance=ProvenanceSource.DATABASE, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=ValidationStatus.NOT_REQUIRED, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="events", columns=(
            ColumnSchema(name="id", data_type="int", nullable=False, ordinal=0),),
            primary_key=("id",)),),
        schema_hash="h1")


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY),
        grains=(GrainStatement(table="events", statement="1 row of events = 1 event",
                               source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9),),
        metric_grains=())


def _governance():
    return GovernanceContext(
        envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM, TrustLevel.SYSTEM),
        sensitive_columns=(), restricted_columns=(), allowed_operations=("SELECT",),
        masking_policy_refs=(), permission_version="p1")


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=0.6, semantic_confidence=0.6,
                         relationship_coverage=0.6, granularity_confidence=0.9,
                         human_validation=0.0, freshness_score=1.0,
                         governance_coverage=1.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATAHEK_DB_PATH"] = str(Path(self._tmp.name) / "datahek.db")
        os.environ["DATAHEK_AUDIT_PATH"] = str(Path(self._tmp.name) / "audit.jsonl")
        container = build_app_container()
        container.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        container.override(ProviderRegistry, registry)
        container.override(ContextBuildJob, _FakeBuildJob())
        self.container = container
        self.client = TestClient(create_app(container))
        self.ctx = RequestContext(source="cli")

    def tearDown(self):
        os.environ.pop("DATAHEK_DB_PATH", None)
        os.environ.pop("DATAHEK_AUDIT_PATH", None)
        self._tmp.cleanup()

    def publish(self):
        service = self.container.resolve(ContextRegistryService)
        return asyncio.run(service.publish(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h1",
            artifacts={
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.GRANULARITY: _granularity(),
                ArtifactKind.GOVERNANCE: _governance(),
            },
            quality=_quality(), freshness=_freshness()))

    def metrics_text(self):
        return self.client.get("/metrics").text


class TestContextMetrics(_Base):
    def test_preview_records_hit_and_tokens(self):
        self.publish()
        resp = self.client.post("/connections/conn1/context/preview",
                                json={"question": "count events"})
        self.assertEqual(resp.status_code, 200)
        text = self.metrics_text()
        self.assertIn('datahek_context_retrievals_total{outcome="hit"} 1', text)
        self.assertIn("datahek_context_tokens_count", text)
        self.assertIn("datahek_context_retrieval_duration_seconds_count", text)

    def test_preview_miss_is_counted(self):
        resp = self.client.post("/connections/none/context/preview",
                                json={"question": "count events"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn('datahek_context_retrievals_total{outcome="miss"} 1', self.metrics_text())

    def test_build_records_outcome_and_duration(self):
        created = self.client.post("/connections", json={"name": "local", "provider": "sqlite"})
        connection_id = created.json()["id"]
        self.client.post(f"/connections/{connection_id}/context/build",
                         json={"enrichment": False})
        text = self.metrics_text()
        self.assertIn('datahek_context_builds_total{outcome="active"} 1', text)
        self.assertIn("datahek_context_build_duration_seconds_count", text)

    def test_unavailable_context_maps_to_503_and_error_metric(self):
        self.container.override(ContextRetriever, _BoomRetriever())
        resp = self.client.post("/connections/conn1/context/preview",
                                json={"question": "count events"})
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body["code"], "CONTEXT_UNAVAILABLE")
        self.assertIn("context store down", body["details"]["reason"])
        self.assertIn('datahek_context_retrievals_total{outcome="error"} 1', self.metrics_text())


class TestContextAudit(_Base):
    def test_build_and_validate_events_are_recorded(self):
        created = self.client.post("/connections", json={"name": "local", "provider": "sqlite"})
        connection_id = created.json()["id"]
        self.client.post(f"/connections/{connection_id}/context/build",
                         json={"enrichment": False})
        self.publish()
        self.client.post("/connections/conn1/context/validate",
                         json={"decisions": [
                             {"kind": "granularity", "index": 0, "action": "approve"}]})
        events = self.client.get("/audit", params={"limit": 50}).json()
        types = {event["event_type"] for event in events}
        self.assertIn("context.build", types)
        self.assertIn("context.validate", types)
        build_event = next(e for e in events if e["event_type"] == "context.build")
        self.assertEqual(build_event["decision"], "ALLOW")
        self.assertIn("connection", build_event["payload"])
        validate_event = next(e for e in events if e["event_type"] == "context.validate")
        self.assertEqual(validate_event["payload"]["decisions"], 1)


if __name__ == "__main__":
    unittest.main()
