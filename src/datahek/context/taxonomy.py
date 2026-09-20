"""TaxonomyService — classification hierarchy derived from profile roles.

Taxonomy answers "what kind of thing is this?" and organizes columns into a
browsable Domain -> Subdomain -> Category tree. It is deterministic (rules +
profile statistics), marked pending_validation for human review, and never
includes sensitive columns (ADR-008, research.md §4).
"""
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ProfileContext,
    ProvenanceSource,
    TaxonomyContext,
    TaxonomyNode,
    TrustLevel,
    ValidationStatus,
)

_CATEGORY_BY_ROLE = {
    "identifier": "Identifier",
    "flag": "Flag",
    "measure": "Measure",
    "temporal": "Temporal",
    "dimension": "Dimension",
}


def build_taxonomy_context(profiles: ProfileContext, *, domain: str = "General",
                           generated_at: str | None = None) -> TaxonomyContext:
    nodes: list[TaxonomyNode] = []
    for table, columns in sorted(profiles.tables.items()):
        subdomain_members = [f"{table}.{column.name}" for column in columns
                             if not column.sensitive and column.role_candidates]
        confidence = 0.8
        if subdomain_members:
            confidences = [value for column in columns
                           for value in column.role_confidence.values()]
            if confidences:
                confidence = round(sum(confidences) / len(confidences), 4)
        nodes.append(TaxonomyNode(
            path=(domain, table),
            members=(table,),
            node_kind="subdomain",
            provenance=ProvenanceSource.SYSTEM,
            validation=ValidationStatus.PENDING,
            confidence=confidence,
        ))
        grouped: dict[str, list[str]] = {}
        for column in columns:
            if column.sensitive:
                continue
            for role in column.role_candidates:
                category = _CATEGORY_BY_ROLE.get(role)
                if category is None:
                    continue
                grouped.setdefault(category, []).append(f"{table}.{column.name}")
                break
        for category, members in sorted(grouped.items()):
            nodes.append(TaxonomyNode(
                path=(domain, table, category),
                members=tuple(members),
                node_kind="category",
                provenance=ProvenanceSource.SYSTEM,
                validation=ValidationStatus.PENDING,
                confidence=confidence,
            ))
    envelope = ArtifactEnvelope(
        kind=ArtifactKind.TAXONOMY,
        schema_version=1,
        provenance=ProvenanceSource.SYSTEM,
        trust=TrustLevel.STRUCTURAL,
        validation=ValidationStatus.PENDING,
        confidence=1.0,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    return TaxonomyContext(envelope=envelope, nodes=tuple(nodes))
