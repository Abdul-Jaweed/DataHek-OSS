"""Data provider contract — the engine routes LogicalPlans to providers (ADR-005, ADR-006)."""
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from datahek.contracts.connections import Connection
from datahek.kernel.context import RequestContext

if TYPE_CHECKING:
    from datahek.engine.schema import SchemaCatalog


class ProviderKind(str, Enum):
    SQL = "sql"
    SEARCH = "search"
    DOCUMENT = "document"
    FILE = "file"
    API = "api"
    VECTOR = "vector"
    GRAPH = "graph"


class ReadOnlyLevel(str, Enum):
    STRUCTURAL = "structural"
    ADVISORY = "advisory"
    NONE = "none"


@dataclass(frozen=True)
class ConnectorCapabilities:
    kind: ProviderKind
    dialect: str | None = None
    features: frozenset[str] = field(default_factory=frozenset)
    read_only: ReadOnlyLevel = ReadOnlyLevel.STRUCTURAL
    max_result_rows: int = 1000
    max_timeout_s: int = 10
    auth_modes: frozenset[str] = field(default_factory=lambda: frozenset({"user_password"}))


@runtime_checkable
class DataProvider(Protocol):
    provider_id: str
    capabilities: ConnectorCapabilities

    async def connect(self, connection: Connection) -> Any: ...
    async def ping(self, client: Any) -> dict: ...
    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> "SchemaCatalog": ...
    async def compile_and_execute(self, client: Any, plan: dict, ctx: RequestContext) -> dict: ...
    async def close(self, client: Any) -> None: ...