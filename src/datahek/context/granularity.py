"""GranularityService — grain statements derived from structural facts.

A single primary key (confirmed by identifier profiling) yields the canonical
`1 row of <table> = 1 <Entity>` statement. Composite keys are qualified, missing
keys are marked unverified. Metric grain maps semantic metrics to their table's
grain with explicit caveats (ADR-013, schema-profiling.md).
"""
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    GrainStatement,
    GranularityContext,
    MetricGrain,
    ProfileContext,
    ProvenanceSource,
    SchemaContext,
    TrustLevel,
    ValidationStatus,
)


def singularize(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith("ies") and len(lowered) > 3:
        return name[:-3] + "y"
    if lowered.endswith(("ses", "xes", "zes", "ches", "shes")):
        return name[:-2]
    if lowered.endswith("s") and not lowered.endswith("ss"):
        return name[:-1]
    return name


def _entity(table: str) -> str:
    return "".join(part.capitalize() for part in singularize(table).split("_"))


def _pk_confidence(table: str, primary_key: tuple[str, ...],
                   profiles: ProfileContext | None) -> float:
    if not primary_key:
        return 0.3
    if len(primary_key) > 1:
        return 0.8
    if profiles is None:
        return 0.7
    column_profiles = profiles.tables.get(table, ())
    profile = next((p for p in column_profiles if p.name == primary_key[0]), None)
    if profile is None:
        return 0.7
    if "identifier" in profile.role_candidates:
        return 0.9
    return 0.6


def build_granularity_context(schema: SchemaContext,
                              profiles: ProfileContext | None = None,
                              *, metrics: Sequence[Mapping] = (),
                              generated_at: str | None = None) -> GranularityContext:
    grains: list[GrainStatement] = []
    by_table: dict[str, GrainStatement] = {}
    for table in schema.tables:
        entity = _entity(table.name)
        confidence = _pk_confidence(table.name, table.primary_key, profiles)
        if table.primary_key:
            if len(table.primary_key) == 1:
                statement = f"1 row of {table.name} = 1 {entity}"
                qualifier = None
            else:
                keys = ", ".join(table.primary_key)
                statement = (f"1 row of {table.name} = 1 {entity} "
                             f"identified by ({keys})")
                qualifier = f"composite key ({keys})"
        else:
            statement = f"1 row of {table.name} = 1 {entity} (unconfirmed)"
            qualifier = "no primary key; grain unverified"
        grain = GrainStatement(
            table=table.name,
            statement=statement,
            qualifier=qualifier,
            entity=entity,
            source=ProvenanceSource.SYSTEM,
            validation=ValidationStatus.PENDING,
            confidence=confidence,
        )
        grains.append(grain)
        by_table[table.name] = grain

    metric_grains: list[MetricGrain] = []
    for metric in metrics:
        table_name = str(metric.get("table", ""))
        grain = by_table.get(table_name)
        if grain is None:
            metric_grains.append(MetricGrain(
                metric=str(metric.get("name", "")),
                valid_at=("unknown",),
                caveat=f"table '{table_name}' not in context",
            ))
            continue
        caveat = None
        if grain.confidence < 0.5:
            caveat = "grain unverified; aggregation may be incorrect"
        metric_grains.append(MetricGrain(
            metric=str(metric.get("name", "")),
            valid_at=(grain.statement,),
            caveat=caveat,
        ))

    envelope = ArtifactEnvelope(
        kind=ArtifactKind.GRANULARITY,
        schema_version=1,
        provenance=ProvenanceSource.SYSTEM,
        trust=TrustLevel.STRUCTURAL,
        validation=ValidationStatus.PENDING,
        confidence=1.0,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    return GranularityContext(envelope=envelope, grains=tuple(grains),
                              metric_grains=tuple(metric_grains))
