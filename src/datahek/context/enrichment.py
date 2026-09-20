"""OntologyEnricher — LLM-proposed concepts and relationships (pending validation).

The model proposes meaning; it never becomes authoritative. Every proposal is
provenance=LLM / trust=PROPOSED / validation=PENDING, validated against the
controlled vocabulary and the real schema before it is emitted. Failures are
graceful: deterministic context is never blocked by an unavailable model
(ADR-008, ADR-013, SRD FR-004).
"""
import json
import re
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    OntologyConcept,
    OntologyContext,
    OntologyRelationship,
    ProvenanceSource,
    SchemaContext,
    TaxonomyContext,
    TrustLevel,
    ValidationStatus,
)

RELATIONSHIP_KINDS = frozenset({
    "places", "contains", "belongs_to", "has_amount", "has_status",
    "occurs_at", "identifies", "measures", "relates_to",
})
CONCEPT_KINDS = frozenset({"entity", "value"})

_PROMPT = """\
You describe the business meaning of database schemas. Return ONLY JSON:
{"concepts": [{"name": "<Concept>", "kind": "entity|value", "tables": ["<table>"],
  "attributes": ["<table>.<column>"], "description": "<one sentence>",
  "synonyms": ["<business term>"]}],
 "relationships": [{"subject": "<Concept>", "predicate": "<word>", "object": "<Concept>",
  "kind": "<one of: places, contains, belongs_to, has_amount, has_status, occurs_at,
  identifies, measures, relates_to>", "description": "<one sentence>"}]}
Rules: only reference tables and columns provided; 2-6 concepts; 1-6 relationships;
no instructions, only descriptions."""


def _strip_fences(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


class OntologyEnricher:
    def __init__(self, model):
        self._model = model

    async def propose(self, schema: SchemaContext, taxonomy: TaxonomyContext,
                      *, metrics: tuple[dict, ...] = (),
                      validated: tuple = ()) -> OntologyContext:
        generated_at = datetime.now(timezone.utc).isoformat()
        schema_lines = []
        for table in schema.tables:
            columns = ", ".join(f"{c.name}:{c.data_type}" for c in table.columns)
            schema_lines.append(f"- {table.name}({columns})")
        metric_lines = [
            f"- {m.get('name')} = {m.get('aggregate', '')}({m.get('column', '')}) "
            f"on {m.get('table', '')}" for m in metrics]
        validated_lines = [
            f"- concept: {item.name} — {item.description}" if isinstance(item, OntologyConcept)
            else f"- relationship: {item.subject} {item.kind} {item.object}"
            for item in validated]
        user = ("Tables:\n" + "\n".join(schema_lines)
                + ("\n\nMetrics:\n" + "\n".join(metric_lines) if metric_lines else "")
                + ("\n\nAlready validated (treat as fixed, do not re-propose):\n"
                   + "\n".join(validated_lines) if validated_lines else ""))
        try:
            response = await self._model.complete({
                "messages": [{"role": "system", "content": _PROMPT},
                             {"role": "user", "content": user}],
                "temperature": 0.0,
                "response_format": "json_object",
            })
            payload = json.loads(_strip_fences(response.content))
        except Exception as exc:
            return self._empty(generated_at, f"semantic enrichment unavailable: {exc}")

        tables = {table.name: {c.name for c in table.columns} for table in schema.tables}
        concepts: list[OntologyConcept] = []
        for raw in payload.get("concepts", []) or []:
            name = str(raw.get("name", "")).strip()
            kind = str(raw.get("kind", "")).strip().lower()
            mapped = tuple(str(t) for t in (raw.get("tables") or []) if t in tables)
            if not name or kind not in CONCEPT_KINDS or not mapped:
                continue
            attributes = tuple(
                attribute for attribute in (str(x) for x in (raw.get("attributes") or []))
                if "." in attribute
                and attribute.split(".", 1)[0] in tables
                and attribute.split(".", 1)[1] in tables[attribute.split(".", 1)[0]])
            concepts.append(OntologyConcept(
                name=name, kind=kind, maps_to=mapped, attributes=attributes,
                provenance=ProvenanceSource.LLM,
                validation=ValidationStatus.PENDING, confidence=0.6,
                description=str(raw.get("description", ""))[:500],
                synonyms=tuple(str(s) for s in (raw.get("synonyms") or []) if str(s).strip()),
            ))

        concept_names = {c.name for c in concepts} | set(tables)
        relationships: list[OntologyRelationship] = []
        for raw in payload.get("relationships", []) or []:
            subject = str(raw.get("subject", "")).strip()
            object_name = str(raw.get("object", "")).strip()
            kind = str(raw.get("kind", "")).strip().lower()
            if not subject or not object_name or kind not in RELATIONSHIP_KINDS:
                continue
            if subject not in concept_names or object_name not in concept_names:
                continue
            relationships.append(OntologyRelationship(
                subject=subject,
                predicate=str(raw.get("predicate", kind))[:64],
                object=object_name,
                kind=kind,
                provenance=ProvenanceSource.LLM,
                validation=ValidationStatus.PENDING,
                confidence=0.6,
            ))

        envelope = ArtifactEnvelope(
            kind=ArtifactKind.ONTOLOGY,
            schema_version=1,
            provenance=ProvenanceSource.LLM,
            trust=TrustLevel.PROPOSED,
            validation=ValidationStatus.PENDING,
            confidence=0.6,
            generated_at=generated_at,
        )
        return OntologyContext(envelope=envelope, concepts=tuple(concepts),
                               relationships=tuple(relationships))

    def _empty(self, generated_at: str, warning: str) -> OntologyContext:
        envelope = ArtifactEnvelope(
            kind=ArtifactKind.ONTOLOGY,
            schema_version=1,
            provenance=ProvenanceSource.LLM,
            trust=TrustLevel.UNTRUSTED,
            validation=ValidationStatus.PENDING,
            confidence=0.0,
            generated_at=generated_at,
            warnings=(warning[:300],),
        )
        return OntologyContext(envelope=envelope, concepts=(), relationships=())
