"""SchemaProfiler — deterministic, privacy-aware column statistics.

One aggregate plan per table runs through the guarded engine (validation,
policy, audit). Sensitive columns contribute counts only; raw text values are
never read (schema-profiling.md).
"""
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnProfile,
    ProfileContext,
    ProvenanceSource,
    TrustLevel,
    ValidationStatus,
)
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode, type_family
from datahek.engine.schema import SchemaCatalog, TableMeta

ARTIFACT_SCHEMA_VERSION = 1

_SENSITIVE_NAME_HINTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey", "ssn",
    "social_security", "credit_card", "card_number", "cvv", "iban", "email", "phone",
)
_IDENTIFIER_UNIQUENESS = 0.99
_DIMENSION_MAX_DISTINCT = 100


def looks_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SENSITIVE_NAME_HINTS)


def _role_candidates(family: str, distinct: int | None, uniqueness: float | None,
                     null_ratio: float, sensitive: bool) -> tuple[tuple[str, ...], dict[str, float]]:
    if sensitive:
        return (), {}
    roles: list[str] = []
    confidence: dict[str, float] = {}
    if uniqueness is not None and uniqueness >= _IDENTIFIER_UNIQUENESS and null_ratio == 0.0:
        roles.append("identifier")
        confidence["identifier"] = round(min(uniqueness, 1.0), 4)
    elif family == "bool" or (distinct is not None and distinct == 2):
        roles.append("flag")
        confidence["flag"] = 0.9
    elif family == "number":
        roles.append("measure")
        confidence["measure"] = 0.9
    if family == "time":
        roles.append("temporal")
        confidence["temporal"] = 1.0
    if family == "string" and distinct is not None and distinct <= _DIMENSION_MAX_DISTINCT \
            and "identifier" not in roles:
        roles.append("dimension")
        confidence["dimension"] = 0.8
    return tuple(roles), confidence


def _as_text(value) -> str | None:
    return None if value is None else str(value)


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SchemaProfiler:
    """Build ProfileContext artifacts through the engine's guarded pipeline."""

    def __init__(self, engine):
        self._engine = engine

    async def profile(self, ctx, connection, catalog: SchemaCatalog, *,
                      tables: list[str] | None = None,
                      include_distinct: bool = True) -> ProfileContext:
        selected = [table for table in catalog.tables
                    if tables is None or table.name in tables]
        profiles: dict[str, tuple[ColumnProfile, ...]] = {}
        for table in selected:
            profiles[table.name] = await self._profile_table(
                ctx, connection, table, include_distinct)
        envelope = ArtifactEnvelope(
            kind=ArtifactKind.PROFILE,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            provenance=ProvenanceSource.DATABASE,
            trust=TrustLevel.STRUCTURAL,
            validation=ValidationStatus.NOT_REQUIRED,
            confidence=1.0,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        return ProfileContext(envelope=envelope, tables=profiles)

    async def _profile_table(self, ctx, connection, table: TableMeta,
                             include_distinct: bool) -> tuple[ColumnProfile, ...]:
        aggregates: list[Aggregate] = [Aggregate(function="count", column="*", alias="n")]
        metadata: list[tuple[str, bool, str]] = []
        for index, column in enumerate(table.columns):
            sensitive = looks_sensitive(column.name)
            family = type_family(column.data_type)
            aggregates.append(Aggregate(function="count", column=column.name,
                                        alias=f"nn_{index}"))
            if include_distinct:
                aggregates.append(Aggregate(function="count_distinct", column=column.name,
                                            alias=f"dc_{index}"))
            if not sensitive and family in ("number", "time"):
                aggregates.append(Aggregate(function="min", column=column.name,
                                            alias=f"mn_{index}"))
                aggregates.append(Aggregate(function="max", column=column.name,
                                            alias=f"mx_{index}"))
            if not sensitive and family == "number":
                aggregates.append(Aggregate(function="avg", column=column.name,
                                            alias=f"av_{index}"))
            metadata.append((column.name, sensitive, family))

        plan = LogicalPlan(nodes=[ReadNode(source=table.name, aggregates=aggregates,
                                           limit=1)])
        result = await self._engine.execute(ctx, plan, connection)
        columns = [c["name"] for c in result.columns]
        row = dict(zip(columns, result.rows[0])) if result.rows else {}
        total = int(row.get("n") or 0)

        profiles: list[ColumnProfile] = []
        for index, (name, sensitive, family) in enumerate(metadata):
            non_null = int(row.get(f"nn_{index}") or 0)
            distinct_raw = row.get(f"dc_{index}") if include_distinct else None
            distinct = int(distinct_raw) if distinct_raw is not None else None
            null_ratio = 1.0 - (non_null / total) if total else 0.0
            uniqueness = (distinct / non_null) if distinct is not None and non_null else None
            if non_null:
                roles, confidence = _role_candidates(family, distinct, uniqueness,
                                                     null_ratio, sensitive)
            else:
                roles, confidence = (), {}
            profiles.append(ColumnProfile(
                name=name,
                row_count=total,
                null_ratio=null_ratio,
                distinct_count=distinct,
                uniqueness_ratio=uniqueness,
                min_value=_as_text(row.get(f"mn_{index}")),
                max_value=_as_text(row.get(f"mx_{index}")),
                avg_value=_as_float(row.get(f"av_{index}")),
                role_candidates=roles,
                role_confidence=confidence,
                sensitive=sensitive,
            ))
        return tuple(profiles)
