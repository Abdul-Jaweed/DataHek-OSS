"""OntologyEnricher — LLM-proposed concepts/relationships, pending validation."""
import asyncio
import json
import unittest

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    OntologyConcept,
    ProfileContext,
    ProvenanceSource,
    TrustLevel,
    ValidationStatus,
)
from datahek.context.enrichment import OntologyEnricher
from datahek.context.snapshot import build_schema_context
from datahek.context.taxonomy import build_taxonomy_context
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta


def _schema():
    catalog = SchemaCatalog(source="c1:appdb", tables=[
        TableMeta(name="orders", columns=[
            ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0),
            ColumnMeta(name="amount", data_type="numeric", ordinal=1)], primary_key=("id",)),
        TableMeta(name="customers", columns=[
            ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0)],
            primary_key=("id",)),
    ])
    return build_schema_context(catalog, database="appdb")


def _taxonomy():
    envelope = ArtifactEnvelope(kind=ArtifactKind.PROFILE, schema_version=1,
                                provenance=ProvenanceSource.DATABASE,
                                trust=TrustLevel.STRUCTURAL,
                                validation=ValidationStatus.NOT_REQUIRED,
                                confidence=1.0, generated_at="t")
    return build_taxonomy_context(ProfileContext(envelope=envelope, tables={}))


class _FakeModel:
    def __init__(self, content):
        self._content = content
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self._content, Exception):
            raise self._content

        class _Response:
            content = self._content

        return _Response()


def _payload():
    return json.dumps({
        "concepts": [
            {"name": "Order", "kind": "entity", "tables": ["orders"],
             "attributes": ["orders.amount"], "description": "a customer order",
             "synonyms": ["purchase"]},
            {"name": "Customer", "kind": "entity", "tables": ["customers"],
             "attributes": [], "description": "a buyer", "synonyms": []},
            {"name": "Ghost", "kind": "entity", "tables": ["missing"],
             "attributes": [], "description": "invalid"},
        ],
        "relationships": [
            {"subject": "Customer", "predicate": "places", "object": "Order",
             "kind": "places", "description": "customers place orders"},
            {"subject": "Order", "predicate": "teleports", "object": "Customer",
             "kind": "teleports", "description": "unknown kind"},
            {"subject": "Ghost", "predicate": "belongs_to", "object": "Order",
             "kind": "belongs_to", "description": "dangling reference"},
        ],
    })


class TestOntologyEnricher(unittest.TestCase):
    def _propose(self, model):
        enricher = OntologyEnricher(model)
        return asyncio.run(enricher.propose(_schema(), _taxonomy()))

    def test_parses_and_filters(self):
        context = self._propose(_FakeModel(_payload()))
        self.assertEqual(context.envelope.kind, ArtifactKind.ONTOLOGY)
        self.assertEqual(context.envelope.provenance, ProvenanceSource.LLM)
        self.assertEqual(context.envelope.trust, TrustLevel.PROPOSED)
        self.assertEqual(context.envelope.validation, ValidationStatus.PENDING)
        names = [c.name for c in context.concepts]
        self.assertEqual(names, ["Order", "Customer"])
        concept = context.concepts[0]
        self.assertEqual(concept.description, "a customer order")
        self.assertEqual(concept.synonyms, ("purchase",))
        kinds = [r.kind for r in context.relationships]
        self.assertEqual(kinds, ["places"])

    def test_drops_invalid_attribute(self):
        payload = json.dumps({"concepts": [
            {"name": "Order", "kind": "entity", "tables": ["orders"],
             "attributes": ["orders.nope"], "description": "", "synonyms": []}],
            "relationships": []})
        context = self._propose(_FakeModel(payload))
        self.assertEqual(context.concepts[0].attributes, ())

    def test_bad_json_is_graceful(self):
        context = self._propose(_FakeModel("not json at all"))
        self.assertEqual(context.concepts, ())
        self.assertTrue(context.envelope.warnings)

    def test_model_failure_is_graceful(self):
        context = self._propose(_FakeModel(RuntimeError("model down")))
        self.assertEqual(context.concepts, ())
        self.assertIn("unavailable", context.envelope.warnings[0])

    def test_validated_items_appear_in_prompt(self):
        model = _FakeModel(_payload())
        enricher = OntologyEnricher(model)
        validated = OntologyConcept(
            name="Order", kind="entity", maps_to=("orders",), attributes=(),
            provenance=ProvenanceSource.HUMAN_VALIDATED,
            validation=ValidationStatus.APPROVED, confidence=0.9,
            description="confirmed order")
        asyncio.run(enricher.propose(_schema(), _taxonomy(), validated=(validated,)))
        user_message = model.requests[0]["messages"][-1]["content"]
        self.assertIn("Already validated", user_message)
        self.assertIn("Order", user_message)


if __name__ == "__main__":
    unittest.main()
