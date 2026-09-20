"""Context Layer contracts — typed artifacts, provenance, and backend protocols."""
import dataclasses
import typing
import unittest

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ContextArtifact,
    ContextPackage,
    ContextRegistry,
    ContextStore,
    GraphPath,
    GraphRelationship,
    GraphNode,
    GraphRepository,
    LifecycleState,
    ProvenanceSource,
    QualityState,
    TrustLevel,
    ValidationStatus,
)


class _FakeRegistry:
    async def register(self, ctx, record): return record.context_id
    async def get(self, ctx, context_id): return None
    async def find(self, ctx, *, connection_id, scope=None, state=None): return []
    async def active(self, ctx, *, connection_id, scope): return None
    async def set_state(self, ctx, context_id, state, reason=""): return None
    async def invalidate(self, ctx, *, connection_id, reason): return 0
    async def versions(self, ctx, *, connection_id, scope): return []


class _FakeStore:
    async def put(self, ctx, context_id, artifact): return None
    async def get(self, ctx, context_id, kind): return None
    async def get_package(self, ctx, context_id): return None


class _FakeGraph:
    async def create_node(self, ctx, node): return node.id
    async def update_node(self, ctx, node): return None
    async def delete_node(self, ctx, node_id): return None
    async def get_node(self, ctx, node_id): return None
    async def find_nodes(self, ctx, *, label, where=None, limit=100): return []
    async def create_relationship(self, ctx, rel): return rel.id
    async def delete_relationship(self, ctx, rel_id): return None
    async def neighbors(self, ctx, node_id, *, rel_type=None, depth=1): return []
    async def paths(self, ctx, *, from_id, to_id, max_depth=3, rel_types=None): return []
    async def health_check(self): return True


class TestEnums(unittest.TestCase):
    def test_lifecycle_states(self):
        self.assertEqual({s.value for s in LifecycleState},
                         {"discovered", "profiling", "enriching", "generated",
                          "pending_validation", "validated", "active", "stale",
                          "rebuilding", "degraded", "failed", "superseded"})

    def test_artifact_kinds(self):
        self.assertEqual({k.value for k in ArtifactKind},
                         {"schema", "profile", "taxonomy", "ontology",
                          "topology", "granularity", "governance", "capability"})

    def test_provenance_and_trust_values(self):
        self.assertEqual({p.value for p in ProvenanceSource},
                         {"database", "system", "llm", "user", "human_validated",
                          "inferred", "imported"})
        self.assertEqual({t.value for t in TrustLevel},
                         {"system", "validated", "structural", "proposed", "untrusted"})
        self.assertEqual({v.value for v in ValidationStatus},
                         {"not_required", "pending", "approved", "edited", "rejected"})
        self.assertEqual({q.value for q in QualityState},
                         {"insufficient", "partial", "sufficient", "validated"})


class TestArtifacts(unittest.TestCase):
    def test_envelope_defaults(self):
        env = ArtifactEnvelope(kind=ArtifactKind.SCHEMA, schema_version=1,
                               provenance=ProvenanceSource.DATABASE,
                               trust=TrustLevel.STRUCTURAL,
                               validation=ValidationStatus.NOT_REQUIRED,
                               confidence=1.0, generated_at="2026-09-21T00:00:00Z")
        self.assertEqual(env.warnings, ())

    def test_artifacts_are_frozen(self):
        env = ArtifactEnvelope(kind=ArtifactKind.GOVERNANCE, schema_version=1,
                               provenance=ProvenanceSource.SYSTEM,
                               trust=TrustLevel.SYSTEM,
                               validation=ValidationStatus.NOT_REQUIRED,
                               confidence=1.0, generated_at="t")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            env.confidence = 0.5  # type: ignore[misc]

    def test_artifact_alias_covers_v1_kinds(self):
        members = set(typing.get_args(ContextArtifact))
        names = {m.__name__ for m in members}
        for expected in ("SchemaContext", "ProfileContext", "TaxonomyContext",
                         "OntologyContext", "TopologyContext", "GranularityContext",
                         "GovernanceContext", "CapabilityContext"):
            self.assertIn(expected, names)
        self.assertEqual(len(members), 8)


class TestProtocols(unittest.TestCase):
    def test_registry_protocol(self):
        self.assertIsInstance(_FakeRegistry(), ContextRegistry)

    def test_store_protocol(self):
        self.assertIsInstance(_FakeStore(), ContextStore)

    def test_graph_protocol(self):
        self.assertIsInstance(_FakeGraph(), GraphRepository)

    def test_graph_models_frozen(self):
        node = GraphNode(id="n1", org_id="default", project_id="default",
                         label="Table", properties={"name": "orders"},
                         context_version=1, schema_hash="h",
                         provenance=ProvenanceSource.DATABASE,
                         created_at="t", updated_at="t")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            node.label = "Column"  # type: ignore[misc]
        rel = GraphRelationship(id="r1", org_id="default", project_id="default",
                                type="HAS_COLUMN", source_id="n1", target_id="n2",
                                context_version=1, schema_hash="h",
                                provenance=ProvenanceSource.DATABASE, confidence=1.0)
        path = GraphPath(nodes=(node,), relationships=(rel,), length=1)
        self.assertEqual(path.length, 1)


if __name__ == "__main__":
    unittest.main()
