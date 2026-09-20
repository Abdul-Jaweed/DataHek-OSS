"""TaxonomyService — role-based classification hierarchy from profile artifacts."""
import unittest

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnProfile,
    ProfileContext,
    ProvenanceSource,
    TrustLevel,
    ValidationStatus,
)
from datahek.context.taxonomy import build_taxonomy_context


def _profiles():
    envelope = ArtifactEnvelope(kind=ArtifactKind.PROFILE, schema_version=1,
                                provenance=ProvenanceSource.DATABASE,
                                trust=TrustLevel.STRUCTURAL,
                                validation=ValidationStatus.NOT_REQUIRED,
                                confidence=1.0, generated_at="t")
    return ProfileContext(envelope=envelope, tables={
        "orders": (
            ColumnProfile(name="order_id", row_count=10, null_ratio=0.0,
                          role_candidates=("identifier",),
                          role_confidence={"identifier": 1.0}),
            ColumnProfile(name="amount", row_count=10, null_ratio=0.0,
                          role_candidates=("measure",),
                          role_confidence={"measure": 0.9}),
            ColumnProfile(name="status", row_count=10, null_ratio=0.0,
                          role_candidates=("dimension",),
                          role_confidence={"dimension": 0.8}),
            ColumnProfile(name="created_at", row_count=10, null_ratio=0.0,
                          role_candidates=("temporal",),
                          role_confidence={"temporal": 1.0}),
            ColumnProfile(name="card_number", row_count=10, null_ratio=0.0,
                          role_candidates=(), sensitive=True),
        ),
    })


class TestTaxonomy(unittest.TestCase):
    def test_builds_hierarchy(self):
        context = build_taxonomy_context(_profiles(), domain="Commerce")
        self.assertEqual(context.envelope.kind, ArtifactKind.TAXONOMY)
        paths = {node.path: node for node in context.nodes}
        subdomain = paths[("Commerce", "orders")]
        self.assertEqual(subdomain.node_kind, "subdomain")
        self.assertEqual(subdomain.members, ("orders",))
        identifiers = paths[("Commerce", "orders", "Identifier")]
        self.assertEqual(identifiers.members, ("orders.order_id",))
        measures = paths[("Commerce", "orders", "Measure")]
        self.assertEqual(measures.members, ("orders.amount",))
        temporal = paths[("Commerce", "orders", "Temporal")]
        self.assertEqual(temporal.members, ("orders.created_at",))

    def test_sensitive_and_untyped_columns_excluded(self):
        context = build_taxonomy_context(_profiles(), domain="Commerce")
        members = tuple(m for node in context.nodes for m in node.members)
        self.assertNotIn("orders.card_number", members)

    def test_node_provenance_is_system_pending(self):
        context = build_taxonomy_context(_profiles(), domain="Commerce")
        category = next(n for n in context.nodes
                        if n.path == ("Commerce", "orders", "Measure"))
        self.assertEqual(category.provenance, ProvenanceSource.SYSTEM)
        self.assertEqual(category.validation, ValidationStatus.PENDING)
        self.assertGreater(category.confidence, 0)


if __name__ == "__main__":
    unittest.main()
