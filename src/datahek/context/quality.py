"""Quality evaluation — per-dimension scores with explicit state thresholds (ADR-009)."""
from datahek.contracts.context import (
    FreshnessReport,
    GovernanceContext,
    GranularityContext,
    OntologyContext,
    ProfileContext,
    QualityReport,
    QualityState,
    SchemaContext,
    TaxonomyContext,
    TopologyContext,
    ValidationStatus,
)

_VALIDATED_STATUSES = (ValidationStatus.APPROVED, ValidationStatus.EDITED)


def _schema_completeness(schema: SchemaContext) -> float:
    columns = [column for table in schema.tables for column in table.columns]
    if not columns:
        return 0.0
    typed = [column for column in columns if column.data_type.strip()]
    return round(len(typed) / len(columns), 4)


def _profiling_coverage(schema: SchemaContext, profiles: ProfileContext | None) -> float:
    columns = [column for table in schema.tables for column in table.columns]
    if not columns or profiles is None:
        return 0.0
    profiled = sum(len(profiles.tables.get(table.name, ())) for table in schema.tables)
    return round(min(profiled / len(columns), 1.0), 4)


def _semantic_confidence(ontology: OntologyContext | None) -> float:
    if ontology is None:
        return 0.0
    confidences = [item.confidence for item in ontology.concepts]
    confidences.extend(item.confidence for item in ontology.relationships)
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)


def _relationship_coverage(schema: SchemaContext, topology: TopologyContext | None) -> float:
    if topology is None or not schema.tables:
        return 0.0
    connected = set()
    for edge in topology.edges:
        connected.add(edge.left.split(".")[0])
        connected.add(edge.right.split(".")[0])
    tables = {table.name for table in schema.tables}
    return round(len(connected & tables) / len(tables), 4)


def _granularity_confidence(granularity: GranularityContext | None) -> float:
    if granularity is None or not granularity.grains:
        return 0.0
    return round(sum(grain.confidence for grain in granularity.grains)
                 / len(granularity.grains), 4)


def _human_validation(ontology: OntologyContext | None,
                      taxonomy: TaxonomyContext | None,
                      granularity: GranularityContext | None) -> float:
    items = []
    if ontology is not None:
        items.extend(ontology.concepts)
        items.extend(ontology.relationships)
    if taxonomy is not None:
        items.extend(taxonomy.nodes)
    if granularity is not None:
        items.extend(granularity.grains)
    reviewable = [item for item in items
                  if item.validation is not ValidationStatus.NOT_REQUIRED]
    if not reviewable:
        return 1.0
    validated = [item for item in reviewable if item.validation in _VALIDATED_STATUSES]
    return round(len(validated) / len(reviewable), 4)


def _freshness_score(freshness: FreshnessReport | None) -> float:
    if freshness is None:
        return 1.0
    return {"fresh": 1.0, "aging": 0.5}.get(freshness.state, 0.0)


def evaluate_quality(*, schema: SchemaContext,
                     profiles: ProfileContext | None = None,
                     topology: TopologyContext | None = None,
                     granularity: GranularityContext | None = None,
                     taxonomy: TaxonomyContext | None = None,
                     ontology: OntologyContext | None = None,
                     governance: GovernanceContext | None = None,
                     freshness: FreshnessReport | None = None) -> QualityReport:
    schema_completeness = _schema_completeness(schema)
    profiling_coverage = _profiling_coverage(schema, profiles)
    semantic_confidence = _semantic_confidence(ontology)
    relationship_coverage = _relationship_coverage(schema, topology)
    granularity_confidence = _granularity_confidence(granularity)
    human_validation = _human_validation(ontology, taxonomy, granularity)
    freshness_score = _freshness_score(freshness)
    governance_coverage = 1.0 if governance is not None else 0.0

    if schema_completeness < 0.5:
        state = QualityState.INSUFFICIENT
    elif profiling_coverage < 0.5:
        state = QualityState.PARTIAL
    elif human_validation == 1.0 and all(
            value >= 0.8 for value in (schema_completeness, profiling_coverage,
                                       semantic_confidence, relationship_coverage,
                                       granularity_confidence, freshness_score)):
        state = QualityState.VALIDATED
    else:
        state = QualityState.SUFFICIENT

    details = {
        "taxonomy_nodes": "" if taxonomy is None else str(len(taxonomy.nodes)),
        "ontology_proposals": "" if ontology is None else
        str(len(ontology.concepts) + len(ontology.relationships)),
    }
    return QualityReport(
        state=state,
        schema_completeness=schema_completeness,
        profiling_coverage=profiling_coverage,
        semantic_confidence=semantic_confidence,
        relationship_coverage=relationship_coverage,
        granularity_confidence=granularity_confidence,
        human_validation=human_validation,
        freshness_score=freshness_score,
        governance_coverage=governance_coverage,
        details=details,
    )
