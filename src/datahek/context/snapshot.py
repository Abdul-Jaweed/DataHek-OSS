"""SchemaContext snapshots — canonical artifacts built from discovered catalogs."""
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    ProvenanceSource,
    SchemaContext,
    TableSchema,
    TrustLevel,
    ValidationStatus,
)
from datahek.context.hashing import schema_hash
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

ARTIFACT_SCHEMA_VERSION = 1


def _column_schema(meta: ColumnMeta, ordinal: int) -> ColumnSchema:
    return ColumnSchema(
        name=meta.name,
        data_type=meta.data_type,
        nullable=meta.nullable,
        ordinal=meta.ordinal if meta.ordinal is not None else ordinal,
        default=meta.default,
        is_primary_key=meta.is_primary_key,
        is_foreign_key=meta.is_foreign_key,
        references=meta.references,
        comment=meta.description,
    )


def _table_schema(meta: TableMeta) -> TableSchema:
    return TableSchema(
        name=meta.name,
        columns=tuple(_column_schema(column, index)
                      for index, column in enumerate(meta.columns)),
        primary_key=tuple(meta.primary_key),
        foreign_keys=tuple(tuple(fk) for fk in meta.foreign_keys),
        indexes=tuple(meta.indexes),
        estimated_rows=meta.row_count,
    )


def build_schema_context(catalog: SchemaCatalog, *, database: str, schema: str = "public",
                         generated_at: str | None = None) -> SchemaContext:
    tables = tuple(_table_schema(table) for table in catalog.tables)
    envelope = ArtifactEnvelope(
        kind=ArtifactKind.SCHEMA,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        provenance=ProvenanceSource.DATABASE,
        trust=TrustLevel.STRUCTURAL,
        validation=ValidationStatus.NOT_REQUIRED,
        confidence=1.0,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    return SchemaContext(envelope=envelope, database=database, schema=schema,
                         tables=tables, schema_hash=schema_hash(tables))
