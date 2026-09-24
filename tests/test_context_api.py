"""Context REST surface — status, build, versions, pending, validate, preview."""
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
    ColumnProfile,
    ColumnSchema,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    ProfileContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
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


def _envelope(kind, provenance=ProvenanceSource.DATABASE, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=ValidationStatus.NOT_REQUIRED, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="events", columns=(
            ColumnSchema(name="id", data_type="int", nullable=False, ordinal=0),
            ColumnSchema(name="amount", data_type="float", nullable=True, ordinal=1)),
            primary_key=("id",)),),
        schema_hash="h1")


def _profiles():
    return ProfileContext(
        envelope=_envelope(ArtifactKind.PROFILE),
        tables={"events": (ColumnProfile(name="amount", row_count=10, null_ratio=0.0),)})


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
        self._tmp.cleanup()

    def publish(self):
        service = self.container.resolve(ContextRegistryService)
        return asyncio.run(service.publish(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h1",
            artifacts={
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.PROFILE: _profiles(),
                ArtifactKind.GRANULARITY: _granularity(),
                ArtifactKind.GOVERNANCE: _governance(),
            },
            quality=_quality(), freshness=_freshness()))


class TestContextApi(_Base):
    def test_status_returns_active_record(self):
        self.publish()
        resp = self.client.get("/connections/conn1/context")
        self.assertEqual(resp.status_code, 200)
        record = resp.json()["context"]
        self.assertEqual(record["version"], 1)
        self.assertEqual(record["state"], "active")

    def test_status_empty_when_no_record(self):
        resp = self.client.get("/connections/none/context")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["context"])

    def test_versions_newest_first(self):
        self.publish()
        self.publish()
        resp = self.client.get("/connections/conn1/context/versions")
        self.assertEqual(resp.status_code, 200)
        versions = resp.json()["versions"]
        self.assertEqual([item["version"] for item in versions], [2, 1])

    def test_pending_lists_reviewable_items(self):
        self.publish()
        resp = self.client.get("/connections/conn1/context/pending")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "granularity")

    def test_validate_publishes_new_version(self):
        self.publish()
        resp = self.client.post("/connections/conn1/context/validate",
                                json={"decisions": [
                                    {"kind": "granularity", "index": 0, "action": "approve"}]})
        self.assertEqual(resp.status_code, 200)
        record = resp.json()["context"]
        self.assertEqual(record["version"], 2)
        self.assertEqual(record["quality"]["human_validation"], 1.0)
        pending = self.client.get("/connections/conn1/context/pending").json()["items"]
        self.assertEqual(pending, [])

    def test_validate_rejects_unknown_kind(self):
        self.publish()
        resp = self.client.post("/connections/conn1/context/validate",
                                json={"decisions": [
                                    {"kind": "nope", "index": 0, "action": "approve"}]})
        self.assertEqual(resp.status_code, 422)

    def test_preview_compiles_package(self):
        self.publish()
        resp = self.client.post("/connections/conn1/context/preview",
                                json={"question": "count events"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual([table["name"] for table in body["tables"]], ["events"])
        self.assertEqual(body["insufficient"], "")
        self.assertEqual(body["trust"], "structural")
        self.assertEqual(body["quality"], "sufficient")
        self.assertGreater(body["tokens"], 0)

    def test_preview_missing_record_is_404(self):
        resp = self.client.post("/connections/none/context/preview",
                                json={"question": "count events"})
        self.assertEqual(resp.status_code, 404)

    def test_build_runs_job(self):
        created = self.client.post("/connections", json={"name": "local", "provider": "sqlite"})
        self.assertEqual(created.status_code, 201)
        connection_id = created.json()["id"]
        resp = self.client.post(f"/connections/{connection_id}/context/build",
                                json={"enrichment": False})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "active")
        self.assertEqual(resp.json()["context_id"], "ctx-built")

    def test_record_endpoint_lists_artifact_kinds(self):
        record = self.publish()
        resp = self.client.get(f"/contexts/{record.context_id}")
        self.assertEqual(resp.status_code, 200)
        kinds = resp.json()["artifact_kinds"]
        self.assertIn("schema", kinds)
        self.assertIn("granularity", kinds)

    def test_record_endpoint_unknown_is_404(self):
        self.assertEqual(self.client.get("/contexts/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TestContextTenantAwareness(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATAHEK_DB_PATH"] = str(Path(self._tmp.name) / "datahek.db")
        container = build_app_container()
        container.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        container.override(ProviderRegistry, registry)
        container.override(ContextBuildJob, _FakeBuildJob())

        from datahek.contracts.auth import AuthenticatedIdentity, AuthProvider
        from datahek.defaults.auth import AuthConfig

        class _AcmeIdentity(AuthenticatedIdentity):
            organization_id: str = "acme"

        class _AcmeAuth:
            async def authenticate(self, *credentials):
                return _AcmeIdentity(user_id="alice", authenticated=True,
                                     roles=frozenset({"admin"}), provider="sso")

            async def authenticate_api_key(self, token):
                return await self.authenticate(token)

        container.override(AuthProvider, _AcmeAuth())
        container.override(AuthConfig, AuthConfig(mode="local"))
        self.container = container
        self.client = TestClient(create_app(container))
        self.headers = {"X-API-Key": "token"}

        service = container.resolve(ContextRegistryService)
        asyncio.run(service.publish(
            RequestContext(source="cli", organization_id="acme"),
            connection_id="acme-conn", scope="connection", schema_hash="h1",
            artifacts={ArtifactKind.SCHEMA: _schema(),
                       ArtifactKind.GOVERNANCE: _governance()},
            quality=_quality(), freshness=_freshness()))

    def tearDown(self):
        os.environ.pop("DATAHEK_DB_PATH", None)
        self._tmp.cleanup()

    def test_status_reads_caller_organization(self):
        response = self.client.get("/connections/acme-conn/context", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["context"])
        self.assertEqual(response.json()["context"]["org_id"], "acme")

    def test_other_organization_sees_nothing(self):
        from datahek.defaults.auth import AuthConfig

        response = self.client.get("/connections/acme-conn/context")
        self.assertEqual(response.status_code, 401)

    def test_pending_and_versions_scoped(self):
        pending = self.client.get("/connections/acme-conn/context/pending",
                                  headers=self.headers)
        self.assertEqual(pending.status_code, 200)
        versions = self.client.get("/connections/acme-conn/context/versions",
                                   headers=self.headers)
        self.assertEqual([v["org_id"] for v in versions.json()["versions"]], ["acme"])


class TestContextPackagePersistence(_Base):
    def test_preview_persist_and_read_package(self):
        self.publish()
        preview = self.client.post("/connections/conn1/context/preview",
                                   json={"question": "count events", "persist": True})
        self.assertEqual(preview.status_code, 200)
        body = preview.json()
        self.assertTrue(body["persisted"])
        package = self.client.get(f"/contexts/{body['context_id']}/package")
        self.assertEqual(package.status_code, 200)
        stored = package.json()["package"]
        self.assertEqual(stored["schema_hash"], body["schema_hash"])
        self.assertEqual(stored["budget"]["tokens_estimate"], body["tokens"])

    def test_preview_without_persist_has_no_package(self):
        record = self.publish()
        self.client.post("/connections/conn1/context/preview",
                         json={"question": "count events"})
        response = self.client.get(f"/contexts/{record.context_id}/package")
        self.assertEqual(response.status_code, 404)

    def test_unknown_package_404(self):
        self.assertEqual(self.client.get("/contexts/missing/package").status_code, 404)

    def test_preview_budget_override_produces_insufficient(self):
        self.publish()
        preview = self.client.post("/connections/conn1/context/preview",
                                   json={"question": "count events", "budget_tokens": 100})
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["insufficient"])


class _FakeQueue:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, ctx, connection_id, scope="connection", enrichment=False,
                      tables=None):
        self.enqueued.append({"connection_id": connection_id, "org": ctx.organization_id})
        return {"id": "job-1", "state": "queued", "connection_id": connection_id}

    def status(self, job_id=None, org_id=None):
        return [{"id": "job-1", "state": "queued"}] if org_id else []


class TestContextRebuildApi(_Base):
    def setUp(self):
        super().setUp()
        from datahek.context.jobs.rebuild_queue import ContextRebuildQueue

        self.queue = _FakeQueue()
        self.container = build_app_container()
        self.container.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        self.container.override(ProviderRegistry, registry)
        self.container.override(ContextBuildJob, _FakeBuildJob())
        self.container.register(ContextRebuildQueue, self.queue, singleton=True)
        # rebuild the client so the app resolves the faked queue
        self.client = TestClient(create_app(self.container))

    def test_enqueue_rebuild(self):
        response = self.client.post("/connections/conn1/context/rebuild?enrichment=true")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["state"], "queued")
        self.assertEqual(self.queue.enqueued[0]["connection_id"], "conn1")

    def test_list_rebuilds(self):
        response = self.client.get("/context/rebuilds")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["jobs"][0]["id"], "job-1")


class TestAutoRebuildHelper(unittest.TestCase):
    def test_enqueues_when_stale_and_enabled(self):
        from datahek.context.jobs.rebuild_queue import maybe_enqueue_rebuild

        queue = _FakeQueue()
        ctx = RequestContext(source="api", organization_id="acme")
        job = asyncio.run(maybe_enqueue_rebuild(queue, ctx, "conn1", "connection",
                                                stale=True, enabled=True))
        self.assertEqual(job["id"], "job-1")
        self.assertEqual(queue.enqueued[0]["org"], "acme")

    def test_skips_when_not_stale_or_disabled_or_missing(self):
        from datahek.context.jobs.rebuild_queue import maybe_enqueue_rebuild

        ctx = RequestContext(source="api")
        queue = _FakeQueue()
        for stale, enabled, target in ((False, True, queue), (True, False, queue),
                                       (True, True, None)):
            self.assertIsNone(asyncio.run(maybe_enqueue_rebuild(
                target, ctx, "conn1", "connection", stale=stale, enabled=enabled)))
        self.assertEqual(queue.enqueued, [])

    def test_enqueue_failure_is_swallowed(self):
        from datahek.context.jobs.rebuild_queue import maybe_enqueue_rebuild

        class _Boom:
            async def enqueue(self, *args, **kwargs):
                raise RuntimeError("queue down")

        ctx = RequestContext(source="api")
        self.assertIsNone(asyncio.run(maybe_enqueue_rebuild(
            _Boom(), ctx, "conn1", "connection", stale=True, enabled=True)))
