"""Typed JSON round-trips for context artifacts, records, and packages.

Writes use ``dataclasses.asdict`` (enums are str-subclasses, so JSON-safe);
reads reconstruct explicitly so tuples and enums survive a JSON round-trip.
"""
import dataclasses

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    CapabilityContext,
    ColumnProfile,
    ColumnSchema,
    ContextBudget,
    ContextPackage,
    ContextRecord,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    JoinEdge,
    LifecycleState,
    MetricGrain,
    OntologyConcept,
    OntologyContext,
    OntologyRelationship,
    ProfileContext,
    ProvenanceEntry,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    SemanticsSummary,
    SkillRef,
    TableSchema,
    TaxonomyContext,
    TaxonomyNode,
    ToolRef,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)


def _envelope(data: dict) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        kind=ArtifactKind(data["kind"]),
        schema_version=data["schema_version"],
        provenance=ProvenanceSource(data["provenance"]),
        trust=TrustLevel(data["trust"]),
        validation=ValidationStatus(data["validation"]),
        confidence=data["confidence"],
        generated_at=data["generated_at"],
        warnings=tuple(data.get("warnings", ())),
    )


def _column_schema(data: dict) -> ColumnSchema:
    return ColumnSchema(
        name=data["name"], data_type=data["data_type"], nullable=data["nullable"],
        ordinal=data["ordinal"], default=data.get("default"),
        is_primary_key=data.get("is_primary_key", False),
        is_foreign_key=data.get("is_foreign_key", False),
        references=data.get("references"), comment=data.get("comment"))


def _table_schema(data: dict) -> TableSchema:
    return TableSchema(
        name=data["name"], columns=tuple(_column_schema(c) for c in data["columns"]),
        primary_key=tuple(data.get("primary_key", ())),
        foreign_keys=tuple(tuple(fk) for fk in data.get("foreign_keys", ())),
        indexes=tuple(data.get("indexes", ())), comment=data.get("comment"),
        estimated_rows=data.get("estimated_rows"))


def _column_profile(data: dict) -> ColumnProfile:
    return ColumnProfile(
        name=data["name"], row_count=data["row_count"], null_ratio=data["null_ratio"],
        distinct_count=data.get("distinct_count"),
        distinct_estimated=data.get("distinct_estimated", False),
        uniqueness_ratio=data.get("uniqueness_ratio"),
        min_value=data.get("min_value"), max_value=data.get("max_value"),
        avg_value=data.get("avg_value"), min_length=data.get("min_length"),
        max_length=data.get("max_length"),
        top_values=tuple(tuple(pair) for pair in data.get("top_values", ())),
        role_candidates=tuple(data.get("role_candidates", ())),
        role_confidence=dict(data.get("role_confidence", {})),
        sensitive=data.get("sensitive", False))


def _taxonomy_node(data: dict) -> TaxonomyNode:
    return TaxonomyNode(
        path=tuple(data["path"]), members=tuple(data["members"]),
        node_kind=data["node_kind"], provenance=ProvenanceSource(data["provenance"]),
        validation=ValidationStatus(data["validation"]), confidence=data["confidence"])


def _ontology_concept(data: dict) -> OntologyConcept:
    return OntologyConcept(
        name=data["name"], kind=data["kind"], maps_to=tuple(data["maps_to"]),
        attributes=tuple(data["attributes"]), provenance=ProvenanceSource(data["provenance"]),
        validation=ValidationStatus(data["validation"]), confidence=data["confidence"],
        description=data.get("description", ""),
        synonyms=tuple(data.get("synonyms", ())))


def _ontology_relationship(data: dict) -> OntologyRelationship:
    return OntologyRelationship(
        subject=data["subject"], predicate=data["predicate"], object=data["object"],
        kind=data["kind"], provenance=ProvenanceSource(data["provenance"]),
        validation=ValidationStatus(data["validation"]), confidence=data["confidence"])


def _join_edge(data: dict) -> JoinEdge:
    return JoinEdge(
        left=data["left"], right=data["right"], kind=data["kind"],
        cardinality=data["cardinality"], fanout_risk=data["fanout_risk"],
        provenance=ProvenanceSource(data["provenance"]), confidence=data["confidence"])


def _grain_statement(data: dict) -> GrainStatement:
    return GrainStatement(
        table=data["table"], statement=data["statement"], qualifier=data.get("qualifier"),
        entity=data.get("entity"), source=ProvenanceSource(data.get("source", "inferred")),
        validation=ValidationStatus(data.get("validation", "pending")),
        confidence=data.get("confidence", 0.5))


def _metric_grain(data: dict) -> MetricGrain:
    return MetricGrain(metric=data["metric"], valid_at=tuple(data["valid_at"]),
                       caveat=data.get("caveat"))


def _skill_ref(data: dict) -> SkillRef:
    return SkillRef(name=data["name"], version=data["version"],
                    precondition=data.get("precondition"))


def _tool_ref(data: dict) -> ToolRef:
    return ToolRef(name=data["name"], kind=data["kind"],
                   scopes=tuple(data.get("scopes", ())))


def artifact_to_dict(artifact) -> dict:
    return dataclasses.asdict(artifact)


def artifact_from_dict(kind: ArtifactKind, data: dict):
    kind = ArtifactKind(kind)
    if kind is ArtifactKind.SCHEMA:
        return SchemaContext(
            envelope=_envelope(data["envelope"]), database=data["database"],
            schema=data["schema"], tables=tuple(_table_schema(t) for t in data["tables"]),
            schema_hash=data["schema_hash"])
    if kind is ArtifactKind.PROFILE:
        return ProfileContext(
            envelope=_envelope(data["envelope"]),
            tables={name: tuple(_column_profile(c) for c in columns)
                    for name, columns in data["tables"].items()},
            sampled=data.get("sampled", False), sample_size=data.get("sample_size"))
    if kind is ArtifactKind.TAXONOMY:
        return TaxonomyContext(
            envelope=_envelope(data["envelope"]),
            nodes=tuple(_taxonomy_node(n) for n in data["nodes"]))
    if kind is ArtifactKind.ONTOLOGY:
        return OntologyContext(
            envelope=_envelope(data["envelope"]),
            concepts=tuple(_ontology_concept(c) for c in data["concepts"]),
            relationships=tuple(_ontology_relationship(r) for r in data["relationships"]))
    if kind is ArtifactKind.TOPOLOGY:
        return TopologyContext(
            envelope=_envelope(data["envelope"]),
            edges=tuple(_join_edge(e) for e in data["edges"]),
            join_paths={key: tuple(tuple(path) for path in paths)
                        for key, paths in data.get("join_paths", {}).items()})
    if kind is ArtifactKind.GRANULARITY:
        return GranularityContext(
            envelope=_envelope(data["envelope"]),
            grains=tuple(_grain_statement(g) for g in data["grains"]),
            metric_grains=tuple(_metric_grain(m) for m in data["metric_grains"]))
    if kind is ArtifactKind.GOVERNANCE:
        return GovernanceContext(
            envelope=_envelope(data["envelope"]),
            sensitive_columns=tuple(data["sensitive_columns"]),
            restricted_columns=tuple(data["restricted_columns"]),
            allowed_operations=tuple(data["allowed_operations"]),
            masking_policy_refs=tuple(data["masking_policy_refs"]),
            permission_version=data["permission_version"])
    if kind is ArtifactKind.CAPABILITY:
        return CapabilityContext(
            envelope=_envelope(data["envelope"]),
            skills=tuple(_skill_ref(s) for s in data["skills"]),
            tools=tuple(_tool_ref(t) for t in data["tools"]),
            providers=tuple(data["providers"]))
    raise ValueError(f"Unsupported artifact kind: {kind}")


def _quality_from_dict(data: dict) -> QualityReport:
    return QualityReport(
        state=QualityState(data["state"]),
        schema_completeness=data["schema_completeness"],
        profiling_coverage=data["profiling_coverage"],
        semantic_confidence=data["semantic_confidence"],
        relationship_coverage=data["relationship_coverage"],
        granularity_confidence=data["granularity_confidence"],
        human_validation=data["human_validation"],
        freshness_score=data["freshness_score"],
        governance_coverage=data["governance_coverage"],
        details=dict(data.get("details", {})))


def _freshness_from_dict(data: dict) -> FreshnessReport:
    return FreshnessReport(
        state=data["state"], age_seconds=data["age_seconds"],
        schema_hash_matches=data["schema_hash_matches"],
        permission_version_matches=data["permission_version_matches"],
        refresh_due_at=data.get("refresh_due_at"))


def record_to_dict(record: ContextRecord) -> dict:
    return dataclasses.asdict(record)


def record_from_dict(data: dict) -> ContextRecord:
    return ContextRecord(
        context_id=data["context_id"], org_id=data["org_id"], project_id=data["project_id"],
        connection_id=data["connection_id"], scope=data["scope"], version=data["version"],
        state=LifecycleState(data["state"]), schema_hash=data["schema_hash"],
        created_at=data["created_at"], updated_at=data["updated_at"],
        artifact_kinds=tuple(ArtifactKind(k) for k in data["artifact_kinds"]),
        quality=_quality_from_dict(data["quality"]),
        freshness=_freshness_from_dict(data["freshness"]),
        previous_version=data.get("previous_version"),
        supersedes=data.get("supersedes"), validated_at=data.get("validated_at"),
        provenance_summary=dict(data.get("provenance_summary", {})),
        notes=data.get("notes", ""))


def package_to_dict(package: ContextPackage) -> dict:
    return dataclasses.asdict(package)


def package_from_dict(data: dict) -> ContextPackage:
    return ContextPackage(
        context_id=data["context_id"], org_id=data["org_id"], project_id=data["project_id"],
        connection_id=data["connection_id"], version=data["version"],
        schema_hash=data["schema_hash"], purpose=data["purpose"],
        generated_at=data["generated_at"],
        schema=tuple(_table_schema(t) for t in data["schema"]),
        profile={name: tuple(_column_profile(c) for c in columns)
                 for name, columns in data["profile"].items()},
        taxonomy=tuple(_taxonomy_node(n) for n in data["taxonomy"]),
        ontology=tuple(_ontology_concept(c) for c in data["ontology"]),
        topology=tuple(_join_edge(e) for e in data["topology"]),
        granularity=tuple(_grain_statement(g) for g in data["granularity"]),
        semantics=SemanticsSummary(
            metrics=tuple(dict(m) for m in data["semantics"]["metrics"]),
            dimensions=tuple(data["semantics"]["dimensions"]),
            identifiers=tuple(data["semantics"]["identifiers"]),
            temporal_fields=tuple(data["semantics"]["temporal_fields"])),
        governance=GovernanceContext(
            envelope=_envelope(data["governance"]["envelope"]),
            sensitive_columns=tuple(data["governance"]["sensitive_columns"]),
            restricted_columns=tuple(data["governance"]["restricted_columns"]),
            allowed_operations=tuple(data["governance"]["allowed_operations"]),
            masking_policy_refs=tuple(data["governance"]["masking_policy_refs"]),
            permission_version=data["governance"]["permission_version"]),
        capabilities=CapabilityContext(
            envelope=_envelope(data["capabilities"]["envelope"]),
            skills=tuple(_skill_ref(s) for s in data["capabilities"]["skills"]),
            tools=tuple(_tool_ref(t) for t in data["capabilities"]["tools"]),
            providers=tuple(data["capabilities"]["providers"])),
        quality=_quality_from_dict(data["quality"]),
        freshness=_freshness_from_dict(data["freshness"]),
        provenance=tuple(ProvenanceEntry(
            field=entry["field"], source=ProvenanceSource(entry["source"]),
            confidence=entry["confidence"],
            validation=ValidationStatus(entry["validation"]),
            note=entry.get("note", "")) for entry in data.get("provenance", ())),
        trust=TrustLevel(data.get("trust", "structural")),
        budget=ContextBudget(
            tokens_estimate=data.get("budget", {}).get("tokens_estimate", 0),
            dropped_sections=tuple(data.get("budget", {}).get("dropped_sections", ()))),
        degraded=tuple(data.get("degraded", ())))
