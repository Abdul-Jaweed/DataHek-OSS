"""Context Layer contracts — typed artifacts, provenance, and backend protocols.

A system prompt is one consumer of context. Artifacts are versioned, provenance-
tagged, and validated (ADR-002, ADR-007). The graph backend is replaceable
(ADR-005); the registry is the source of truth for lifecycle (ADR-006).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from datahek.kernel.context import RequestContext


class ArtifactKind(str, Enum):
    SCHEMA = "schema"
    PROFILE = "profile"
    TAXONOMY = "taxonomy"
    ONTOLOGY = "ontology"
    TOPOLOGY = "topology"
    GRANULARITY = "granularity"
    GOVERNANCE = "governance"
    CAPABILITY = "capability"


class LifecycleState(str, Enum):
    DISCOVERED = "discovered"
    PROFILING = "profiling"
    ENRICHING = "enriching"
    GENERATED = "generated"
    PENDING_VALIDATION = "pending_validation"
    VALIDATED = "validated"
    ACTIVE = "active"
    STALE = "stale"
    REBUILDING = "rebuilding"
    DEGRADED = "degraded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ProvenanceSource(str, Enum):
    DATABASE = "database"
    SYSTEM = "system"
    LLM = "llm"
    USER = "user"
    HUMAN_VALIDATED = "human_validated"
    INFERRED = "inferred"
    IMPORTED = "imported"


class TrustLevel(str, Enum):
    SYSTEM = "system"
    VALIDATED = "validated"
    STRUCTURAL = "structural"
    PROPOSED = "proposed"
    UNTRUSTED = "untrusted"


class ValidationStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class QualityState(str, Enum):
    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"
    SUFFICIENT = "sufficient"
    VALIDATED = "validated"


@dataclass(frozen=True)
class ArtifactEnvelope:
    kind: ArtifactKind
    schema_version: int
    provenance: ProvenanceSource
    trust: TrustLevel
    validation: ValidationStatus
    confidence: float
    generated_at: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool
    ordinal: int
    default: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[ColumnSchema, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[tuple[str, str], ...] = ()
    indexes: tuple[str, ...] = ()
    comment: str | None = None
    estimated_rows: int | None = None


@dataclass(frozen=True)
class SchemaContext:
    envelope: ArtifactEnvelope
    database: str
    schema: str
    tables: tuple[TableSchema, ...]
    schema_hash: str


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    row_count: int
    null_ratio: float
    distinct_count: int | None = None
    distinct_estimated: bool = False
    uniqueness_ratio: float | None = None
    min_value: str | None = None
    max_value: str | None = None
    avg_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    top_values: tuple[tuple[str, int], ...] = ()
    role_candidates: tuple[str, ...] = ()
    role_confidence: dict[str, float] = field(default_factory=dict)
    sensitive: bool = False


@dataclass(frozen=True)
class ProfileContext:
    envelope: ArtifactEnvelope
    tables: dict[str, tuple[ColumnProfile, ...]]
    sampled: bool = False
    sample_size: int | None = None


@dataclass(frozen=True)
class TaxonomyNode:
    path: tuple[str, ...]
    members: tuple[str, ...]
    node_kind: str
    provenance: ProvenanceSource
    validation: ValidationStatus
    confidence: float


@dataclass(frozen=True)
class TaxonomyContext:
    envelope: ArtifactEnvelope
    nodes: tuple[TaxonomyNode, ...]


@dataclass(frozen=True)
class OntologyConcept:
    name: str
    kind: str
    maps_to: tuple[str, ...]
    attributes: tuple[str, ...]
    provenance: ProvenanceSource
    validation: ValidationStatus
    confidence: float
    description: str = ""
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class OntologyRelationship:
    subject: str
    predicate: str
    object: str
    kind: str
    provenance: ProvenanceSource
    validation: ValidationStatus
    confidence: float


@dataclass(frozen=True)
class OntologyContext:
    envelope: ArtifactEnvelope
    concepts: tuple[OntologyConcept, ...]
    relationships: tuple[OntologyRelationship, ...]


@dataclass(frozen=True)
class JoinEdge:
    left: str
    right: str
    kind: str
    cardinality: str
    fanout_risk: str
    provenance: ProvenanceSource
    confidence: float


@dataclass(frozen=True)
class TopologyContext:
    envelope: ArtifactEnvelope
    edges: tuple[JoinEdge, ...]
    join_paths: dict[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class GrainStatement:
    table: str
    statement: str
    qualifier: str | None = None
    entity: str | None = None
    source: ProvenanceSource = ProvenanceSource.INFERRED
    validation: ValidationStatus = ValidationStatus.PENDING
    confidence: float = 0.5


@dataclass(frozen=True)
class MetricGrain:
    metric: str
    valid_at: tuple[str, ...]
    caveat: str | None = None


@dataclass(frozen=True)
class GranularityContext:
    envelope: ArtifactEnvelope
    grains: tuple[GrainStatement, ...]
    metric_grains: tuple[MetricGrain, ...]


@dataclass(frozen=True)
class GovernanceContext:
    envelope: ArtifactEnvelope
    sensitive_columns: tuple[str, ...]
    restricted_columns: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    masking_policy_refs: tuple[str, ...]
    permission_version: str


@dataclass(frozen=True)
class SkillRef:
    name: str
    version: str
    precondition: str | None = None


@dataclass(frozen=True)
class ToolRef:
    name: str
    kind: str
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityContext:
    envelope: ArtifactEnvelope
    skills: tuple[SkillRef, ...]
    tools: tuple[ToolRef, ...]
    providers: tuple[str, ...]


ContextArtifact = (
    SchemaContext | ProfileContext | TaxonomyContext | OntologyContext
    | TopologyContext | GranularityContext | GovernanceContext | CapabilityContext
)


@dataclass(frozen=True)
class SemanticsSummary:
    metrics: tuple[dict, ...]
    dimensions: tuple[str, ...]
    identifiers: tuple[str, ...]
    temporal_fields: tuple[str, ...]


@dataclass(frozen=True)
class QualityReport:
    state: QualityState
    schema_completeness: float
    profiling_coverage: float
    semantic_confidence: float
    relationship_coverage: float
    granularity_confidence: float
    human_validation: float
    freshness_score: float
    governance_coverage: float
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FreshnessReport:
    state: str
    age_seconds: int
    schema_hash_matches: bool
    permission_version_matches: bool
    refresh_due_at: str | None = None


@dataclass(frozen=True)
class ProvenanceEntry:
    field: str
    source: ProvenanceSource
    confidence: float
    validation: ValidationStatus
    note: str = ""


@dataclass(frozen=True)
class ContextBudget:
    tokens_estimate: int
    dropped_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextPackage:
    context_id: str
    org_id: str
    project_id: str
    connection_id: str
    version: int
    schema_hash: str
    purpose: str
    generated_at: str
    schema: tuple[TableSchema, ...]
    profile: dict[str, tuple[ColumnProfile, ...]]
    taxonomy: tuple[TaxonomyNode, ...]
    ontology: tuple[OntologyConcept, ...]
    topology: tuple[JoinEdge, ...]
    granularity: tuple[GrainStatement, ...]
    semantics: SemanticsSummary
    governance: GovernanceContext
    capabilities: CapabilityContext
    quality: QualityReport
    freshness: FreshnessReport
    provenance: tuple[ProvenanceEntry, ...] = ()
    trust: TrustLevel = TrustLevel.STRUCTURAL
    budget: ContextBudget = field(default_factory=lambda: ContextBudget(tokens_estimate=0))
    degraded: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextRecord:
    context_id: str
    org_id: str
    project_id: str
    connection_id: str
    scope: str
    version: int
    state: LifecycleState
    schema_hash: str
    created_at: str
    updated_at: str
    artifact_kinds: tuple[ArtifactKind, ...]
    quality: QualityReport
    freshness: FreshnessReport
    previous_version: int | None = None
    supersedes: str | None = None
    validated_at: str | None = None
    provenance_summary: dict[str, int] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class GraphNode:
    id: str
    org_id: str
    project_id: str
    label: str
    properties: dict[str, str]
    context_version: int
    schema_hash: str
    provenance: ProvenanceSource
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GraphRelationship:
    id: str
    org_id: str
    project_id: str
    type: str
    source_id: str
    target_id: str
    context_version: int
    schema_hash: str
    provenance: ProvenanceSource
    confidence: float
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPath:
    nodes: tuple[GraphNode, ...]
    relationships: tuple[GraphRelationship, ...]
    length: int


@runtime_checkable
class ContextRegistry(Protocol):
    async def register(self, ctx: RequestContext, record: ContextRecord) -> str: ...
    async def get(self, ctx: RequestContext, context_id: str) -> ContextRecord | None: ...
    async def find(self, ctx: RequestContext, *, connection_id: str,
                   scope: str | None = None,
                   state: LifecycleState | None = None) -> list[ContextRecord]: ...
    async def active(self, ctx: RequestContext, *, connection_id: str,
                     scope: str) -> ContextRecord | None: ...
    async def set_state(self, ctx: RequestContext, context_id: str,
                        state: LifecycleState, reason: str = "") -> None: ...
    async def invalidate(self, ctx: RequestContext, *, connection_id: str,
                         reason: str) -> int: ...
    async def versions(self, ctx: RequestContext, *, connection_id: str,
                       scope: str) -> list[ContextRecord]: ...


@runtime_checkable
class ContextStore(Protocol):
    async def put(self, ctx: RequestContext, context_id: str,
                  artifact: ContextArtifact) -> None: ...
    async def get(self, ctx: RequestContext, context_id: str,
                  kind: ArtifactKind) -> ContextArtifact | None: ...
    async def get_package(self, ctx: RequestContext,
                          context_id: str) -> ContextPackage | None: ...


@dataclass(frozen=True)
class RuntimeContext:
    question: str
    purpose: str = "sql.planner"


@dataclass(frozen=True)
class RetrievedContext:
    context_id: str
    version: int
    schema_hash: str
    scope: str
    connection_id: str
    schema: tuple[TableSchema, ...]
    profiles: dict[str, tuple[ColumnProfile, ...]]
    topology: TopologyContext | None
    granularity: GranularityContext | None
    taxonomy: TaxonomyContext | None
    ontology: OntologyContext | None
    governance: GovernanceContext | None
    metrics: tuple[dict, ...]
    quality: QualityReport
    freshness: FreshnessReport
    stale: bool = False


@dataclass(frozen=True)
class ComposedContext:
    context_id: str
    version: int
    schema_hash: str
    scope: str
    connection_id: str
    purpose: str
    schema: tuple[TableSchema, ...]
    profiles: dict[str, tuple[ColumnProfile, ...]]
    topology: TopologyContext | None
    granularity: GranularityContext | None
    taxonomy: TaxonomyContext | None
    ontology: OntologyContext | None
    governance: GovernanceContext | None
    metrics: tuple[dict, ...]
    dropped: tuple[str, ...] = ()
    tokens_estimate: int = 0
    insufficient_reason: str = ""


@runtime_checkable
class ContextRetriever(Protocol):
    async def retrieve(self, ctx: RequestContext, *, connection_id: str, question: str,
                       scope: str = "connection",
                       current_schema_hash: str | None = None) -> RetrievedContext | None: ...


@runtime_checkable
class ContextComposer(Protocol):
    async def compose(self, ctx: RequestContext, retrieved: RetrievedContext,
                      runtime: RuntimeContext, *,
                      budget_tokens: int = 4000) -> ComposedContext: ...


@runtime_checkable
class ContextCompiler(Protocol):
    async def compile(self, ctx: RequestContext, composed: ComposedContext, *,
                      quality: QualityReport, freshness: FreshnessReport,
                      governance: GovernanceContext | None = None,
                      skills: tuple[SkillRef, ...] = (),
                      tools: tuple[ToolRef, ...] = (),
                      providers: tuple[str, ...] = ()) -> ContextPackage: ...


@runtime_checkable
class GraphRepository(Protocol):
    async def create_node(self, ctx: RequestContext, node: GraphNode) -> str: ...
    async def update_node(self, ctx: RequestContext, node: GraphNode) -> None: ...
    async def delete_node(self, ctx: RequestContext, node_id: str) -> None: ...
    async def get_node(self, ctx: RequestContext, node_id: str) -> GraphNode | None: ...
    async def find_nodes(self, ctx: RequestContext, *, label: str,
                         where: dict | None = None, limit: int = 100) -> list[GraphNode]: ...
    async def create_relationship(self, ctx: RequestContext,
                                  rel: GraphRelationship) -> str: ...
    async def delete_relationship(self, ctx: RequestContext, rel_id: str) -> None: ...
    async def neighbors(self, ctx: RequestContext, node_id: str, *,
                        rel_type: str | None = None, depth: int = 1) -> list[GraphNode]: ...
    async def paths(self, ctx: RequestContext, *, from_id: str, to_id: str,
                    max_depth: int = 3,
                    rel_types: list[str] | None = None) -> list[GraphPath]: ...
    async def health_check(self) -> bool: ...
