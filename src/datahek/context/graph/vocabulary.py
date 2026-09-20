"""Controlled relationship vocabulary — new edge types require an ADR update (ADR-003)."""
from datahek.kernel.errors import DatahekError, ErrorCode

KNOWN_RELATIONSHIP_TYPES = frozenset({
    "OWNS", "HAS_SCHEMA", "HAS_TABLE", "HAS_COLUMN", "HAS_METRIC", "HAS_DIMENSION",
    "REFERENCES", "JOINS_WITH", "INSTANCE_OF", "BELONGS_TO", "SEMANTICALLY_RELATED_TO",
    "MEASURES", "IDENTIFIES", "OCCURS_AT", "DESCRIBES", "VALIDATED_BY",
})


def assert_relationship_type(name: str) -> str:
    if name not in KNOWN_RELATIONSHIP_TYPES:
        raise DatahekError(
            ErrorCode.VALIDATION,
            f"Unknown graph relationship type '{name}'",
            details={"known": sorted(KNOWN_RELATIONSHIP_TYPES)},
        )
    return name
