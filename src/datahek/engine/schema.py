"""Schema catalog and discovery service — grounds planning in real schema."""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from datahek.contracts.connections import Connection
from datahek.contracts.providers import DataProvider
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None
    semantic_tags: frozenset[str] = field(default_factory=frozenset)
    default: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: str | None = None
    ordinal: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "description": self.description,
            "semantic_tags": sorted(self.semantic_tags),
            "default": self.default,
            "is_primary_key": self.is_primary_key,
            "is_foreign_key": self.is_foreign_key,
            "references": self.references,
            "ordinal": self.ordinal,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ColumnMeta":
        return cls(
            name=data["name"],
            data_type=data["data_type"],
            nullable=data.get("nullable", True),
            description=data.get("description"),
            semantic_tags=frozenset(data.get("semantic_tags", [])),
            default=data.get("default"),
            is_primary_key=data.get("is_primary_key", False),
            is_foreign_key=data.get("is_foreign_key", False),
            references=data.get("references"),
            ordinal=data.get("ordinal", 0),
        )


@dataclass(frozen=True)
class TableMeta:
    name: str
    columns: list[ColumnMeta] = field(default_factory=list)
    kind: str = "table"
    row_count: int | None = None
    sensitive_tags: frozenset[str] = field(default_factory=frozenset)
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[tuple[str, str], ...] = ()
    indexes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "row_count": self.row_count,
            "columns": [c.to_dict() for c in self.columns],
            "sensitive_tags": sorted(self.sensitive_tags),
            "primary_key": list(self.primary_key),
            "foreign_keys": [list(fk) for fk in self.foreign_keys],
            "indexes": list(self.indexes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TableMeta":
        return cls(
            name=data["name"],
            kind=data.get("kind", "table"),
            row_count=data.get("row_count"),
            columns=[ColumnMeta.from_dict(c) for c in data.get("columns", [])],
            sensitive_tags=frozenset(data.get("sensitive_tags", [])),
            primary_key=tuple(data.get("primary_key", [])),
            foreign_keys=tuple(tuple(fk) for fk in data.get("foreign_keys", [])),
            indexes=tuple(data.get("indexes", [])),
        )


@dataclass(frozen=True)
class SchemaCatalog:
    source: str  # "<connection_id>:<database>"
    tables: list[TableMeta] = field(default_factory=list)
    version: int = 1
    refreshed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "version": self.version,
            "refreshed_at": self.refreshed_at,
            "tables": [t.to_dict() for t in self.tables],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaCatalog":
        return cls(
            source=data["source"],
            version=data.get("version", 1),
            refreshed_at=data.get("refreshed_at", ""),
            tables=[TableMeta.from_dict(t) for t in data.get("tables", [])],
        )


@dataclass
class _CatalogEntry:
    catalog: SchemaCatalog
    fetched_at: float


class SchemaService:
    """Discover + cache schema catalogs per connection (TTL refresh)."""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._entries: dict[str, _CatalogEntry] = {}

    def _key(self, connection: Connection) -> str:
        return f"{connection.id}:{connection.database or 'default'}"

    async def get_catalog(
        self,
        ctx: RequestContext,
        connection: Connection,
        provider: DataProvider,
        force_refresh: bool = False,
    ) -> SchemaCatalog:
        key = self._key(connection)
        entry = self._entries.get(key)
        now = time.time()
        if not force_refresh and entry and (now - entry.fetched_at) < self._ttl:
            return entry.catalog
        try:
            catalog = await provider.introspect(ctx, connection, key)
        except DatahekError:
            raise
        except Exception as e:
            logger.exception("Schema discovery failed for %s", connection.name)
            raise DatahekError(
                ErrorCode.CONNECTION_FAILED,
                f"Schema discovery failed for '{connection.name}'",
                details={"connection": connection.name},
            ) from e
        self._entries[key] = _CatalogEntry(catalog=catalog, fetched_at=now)
        return catalog

    def tables(self, catalog: SchemaCatalog) -> set[str]:
        return {t.name for t in catalog.tables}

    def columns(self, catalog: SchemaCatalog) -> dict[str, set[str]]:
        return {t.name: {c.name for c in t.columns} for t in catalog.tables}

    def column_types(self, catalog: SchemaCatalog) -> dict[str, dict[str, str]]:
        return {t.name: {c.name: c.data_type for c in t.columns} for t in catalog.tables}