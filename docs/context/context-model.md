# Context Layer — Context Model

**Status:** Milestone 2 deliverable — proposed for review
**Related:** [architecture.md](architecture.md) · ADR-007 (Context Package Model)

All types below are **frozen dataclasses** in `contracts/context.py` (convention-fit decision).
Pydantic schemas mirror them at the API boundary only. Nothing here is a free-form dict except
small, schema-versioned `properties` maps on graph nodes/edges.

---

## 1. Enumerations

```python
class ArtifactKind(str, Enum):
    SCHEMA = "schema"; PROFILE = "profile"; TAXONOMY = "taxonomy"; ONTOLOGY = "ontology"
    TOPOLOGY = "topology"; GRANULARITY = "granularity"; GOVERNANCE = "governance"
    CAPABILITY = "capability"

class LifecycleState(str, Enum):
    DISCOVERED = "discovered"; PROFILING = "profiling"; ENRICHING = "enriching"
    GENERATED = "generated"; PENDING_VALIDATION = "pending_validation"
    VALIDATED = "validated"; ACTIVE = "active"; STALE = "stale"
    REBUILDING = "rebuilding"; DEGRADED = "degraded"; FAILED = "failed"
    SUPERSEDED = "superseded"

class ProvenanceSource(str, Enum):
    DATABASE = "database"; SYSTEM = "system"; LLM = "llm"; USER = "user"
    HUMAN_VALIDATED = "human_validated"; INFERRED = "inferred"; IMPORTED = "imported"

class TrustLevel(str, Enum):
    SYSTEM = "system"                  # code-owned
    VALIDATED = "validated"            # human-approved or deterministic database facts
    STRUCTURAL = "structural"          # deterministic catalog/statistics facts
    PROPOSED = "proposed"              # LLM/user proposals, not yet validated
    UNTRUSTED = "untrusted"            # comments, sample values, external text

class ValidationStatus(str, Enum):
    NOT_REQUIRED = "not_required"; PENDING = "pending"
    APPROVED = "approved"; EDITED = "edited"; REJECTED = "rejected"

class QualityState(str, Enum):
    INSUFFICIENT = "insufficient"; PARTIAL = "partial"
    SUFFICIENT = "sufficient"; VALIDATED = "validated"
```

## 2. Registry record

```python
@dataclass(frozen=True)
class ContextRecord:
    context_id: str                    # entity id
    org_id: str; project_id: str
    connection_id: str
    scope: str                         # "connection" or "table:<name>"
    version: int                       # monotonic per scope
    state: LifecycleState
    schema_hash: str                   # canonical SHA-256 of the scope's schema
    previous_version: int | None
    supersedes: str | None             # context_id of the prior version
    created_at: str; updated_at: str
    validated_at: str | None
    quality: "QualityReport"
    freshness: "FreshnessReport"
    artifact_kinds: tuple[ArtifactKind, ...]
    provenance_summary: dict[str, int] # source -> count
    notes: str = ""
```

## 3. Artifacts

Every artifact carries the same envelope:

```python
@dataclass(frozen=True)
class ArtifactEnvelope:
    kind: ArtifactKind
    schema_version: int                # artifact schema version (not context version)
    provenance: ProvenanceSource
    trust: TrustLevel
    validation: ValidationStatus
    confidence: float                  # 0..1, deterministic facts = 1.0
    generated_at: str
    warnings: tuple[str, ...] = ()
```

### 3.1 SchemaContext

```python
@dataclass(frozen=True)
class ColumnSchema:
    name: str; data_type: str; nullable: bool
    default: str | None; ordinal: int
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: str | None = None      # "table.column"

@dataclass(frozen=True)
class TableSchema:
    name: str; columns: tuple[ColumnSchema, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[tuple[str, str], ...]   # (column, "table.column")
    indexes: tuple[str, ...]
    comment: str | None = None         # UNTRUSTED trust level when present
    estimated_rows: int | None = None

@dataclass(frozen=True)
class SchemaContext:
    envelope: ArtifactEnvelope         # provenance=DATABASE, trust=STRUCTURAL, confidence=1.0
    database: str; schema: str
    tables: tuple[TableSchema, ...]
    schema_hash: str
```

### 3.2 ProfileContext

```python
@dataclass(frozen=True)
class ColumnProfile:
    name: str
    row_count: int
    null_ratio: float
    distinct_count: int | None
    distinct_estimated: bool           # True when sample-derived
    uniqueness_ratio: float | None
    min_value: str | None; max_value: str | None   # normalized to string
    avg_value: float | None            # numeric only
    min_length: int | None; max_length: int | None # text only
    top_values: tuple[tuple[str, int], ...]        # bucketed enums, k<=20, non-sensitive only
    role_candidates: tuple[str, ...]   # identifier|dimension|measure|temporal|flag
    role_confidence: dict[str, float]
    sensitive: bool                    # governance-classified at build time

@dataclass(frozen=True)
class ProfileContext:
    envelope: ArtifactEnvelope         # provenance=DATABASE, trust=STRUCTURAL
    tables: dict[str, tuple[ColumnProfile, ...]]
    sampled: bool
    sample_size: int | None
```

### 3.3 TaxonomyContext

```python
@dataclass(frozen=True)
class TaxonomyNode:
    path: tuple[str, ...]              # ("Commerce", "Orders", "Measures")
    members: tuple[str, ...]           # "table.column" or "table"
    node_kind: str                     # domain|subdomain|entity|category(Identifier, Measure, Dimension, Temporal, ...)
    provenance: ProvenanceSource
    validation: ValidationStatus
    confidence: float

@dataclass(frozen=True)
class TaxonomyContext:
    envelope: ArtifactEnvelope
    nodes: tuple[TaxonomyNode, ...]
```

### 3.4 OntologyContext

```python
@dataclass(frozen=True)
class OntologyConcept:
    name: str                          # "Order", "Customer"
    kind: str                          # entity|value
    maps_to: tuple[str, ...]           # table names
    attributes: tuple[str, ...]        # "table.column"
    provenance: ProvenanceSource; validation: ValidationStatus; confidence: float

@dataclass(frozen=True)
class OntologyRelationship:
    subject: str; predicate: str; object: str   # Customer places Order
    kind: str                          # has_amount|belongs_to|occurs_at|contains|places|identifies
    provenance: ProvenanceSource; validation: ValidationStatus; confidence: float

@dataclass(frozen=True)
class OntologyContext:
    envelope: ArtifactEnvelope
    concepts: tuple[OntologyConcept, ...]
    relationships: tuple[OntologyRelationship, ...]
```

### 3.5 TopologyContext

```python
@dataclass(frozen=True)
class JoinEdge:
    left: str                          # "orders.customer_id"
    right: str                         # "customers.id"
    kind: str                          # fk | inferred
    cardinality: str                   # 1:1 | 1:N | N:1 | N:M | unknown
    fanout_risk: str                   # none|low|medium|high (duplicate-key risk)
    provenance: ProvenanceSource; confidence: float

@dataclass(frozen=True)
class TopologyContext:
    envelope: ArtifactEnvelope
    edges: tuple[JoinEdge, ...]
    join_paths: dict[str, tuple[tuple[str, ...], ...]]   # "a->b" -> paths (max depth 3)
```

### 3.6 GranularityContext

```python
@dataclass(frozen=True)
class GrainStatement:
    table: str
    statement: str                     # "1 row of orders = 1 Order"
    qualifier: str | None              # e.g. "line item within an order"
    entity: str | None
    source: ProvenanceSource; validation: ValidationStatus; confidence: float

@dataclass(frozen=True)
class MetricGrain:
    metric: str                        # metric name
    valid_at: tuple[str, ...]          # grains where valid
    caveat: str | None                 # e.g. "double-counts if joined to order_items"

@dataclass(frozen=True)
class GranularityContext:
    envelope: ArtifactEnvelope
    grains: tuple[GrainStatement, ...]
    metric_grains: tuple[MetricGrain, ...]
```

### 3.7 GovernanceContext

```python
@dataclass(frozen=True)
class GovernanceContext:
    envelope: ArtifactEnvelope         # provenance=SYSTEM/DATABASE
    sensitive_columns: tuple[str, ...] # "table.column"
    restricted_columns: tuple[str, ...]
    allowed_operations: tuple[str, ...]# ("SELECT",)
    masking_policy_refs: tuple[str, ...]
    permission_version: str            # invalidates caches on change
```

### 3.8 CapabilityContext

```python
@dataclass(frozen=True)
class SkillRef:   name: str; version: str; precondition: str | None = None
@dataclass(frozen=True)
class ToolRef:    name: str; kind: str; scopes: tuple[str, ...] = ()

@dataclass(frozen=True)
class CapabilityContext:
    envelope: ArtifactEnvelope         # provenance=SYSTEM
    skills: tuple[SkillRef, ...]       # matched on demand, not bulk-injected
    tools: tuple[ToolRef, ...]
    providers: tuple[str, ...]         # provider ids available for this connection
```

## 4. Context Package

The compiler's deterministic output for one `purpose`, consumed by one agent call.

```python
@dataclass(frozen=True)
class ContextPackage:
    context_id: str
    org_id: str; project_id: str
    connection_id: str
    version: int
    schema_hash: str

    purpose: str                       # "sql.planner" (V1)
    generated_at: str

    # Relevant slices only — never the whole store or graph
    schema: tuple[TableSchema, ...]
    profile: dict[str, tuple[ColumnProfile, ...]]        # table -> relevant column profiles
    taxonomy: tuple[TaxonomyNode, ...]
    ontology: tuple[OntologyConcept, ...]
    topology: tuple[JoinEdge, ...]
    granularity: tuple[GrainStatement, ...]

    semantics: "SemanticsSummary"      # validated metrics/dimensions/identifiers/temporal
    governance: GovernanceContext
    capabilities: CapabilityContext

    quality: "QualityReport"
    freshness: "FreshnessReport"
    provenance: tuple["ProvenanceEntry", ...]            # field-scoped where meaningful
    trust: TrustLevel                  # package-level floor (min across included content)

    budget: "ContextBudget"            # tokens_estimate, dropped_sections
    degraded: tuple[str, ...]          # sections dropped or unavailable

@dataclass(frozen=True)
class SemanticsSummary:
    metrics: tuple[dict, ...]          # existing Metric shape (id, name, table, aggregate, column, filter, description)
    dimensions: tuple[str, ...]        # "table.column"
    identifiers: tuple[str, ...]
    temporal_fields: tuple[str, ...]
```

**Package rules**

1. A package never includes a full schema: only tables/columns selected by retrieval, plus the
   join edges needed between them.
2. Governance and granularity are **never dropped** by budgeting; if they cannot be included the
   retrieval/compile step fails closed (`QualityState.INSUFFICIENT`).
3. Every included section records its provenance; the package `trust` is the minimum trust of
   included content.
4. Packages are immutable and versioned by `(context_id, version, purpose, retrieval_digest)`.

## 5. Quality and freshness reports

```python
@dataclass(frozen=True)
class QualityReport:
    state: QualityState
    schema_completeness: float         # columns known / columns declared
    profiling_coverage: float          # profiled columns / columns
    semantic_confidence: float         # mean confidence of validated+proposed semantics
    relationship_coverage: float       # connected tables / tables
    granularity_confidence: float
    human_validation: float            # validated proposals / proposals
    freshness_score: float
    governance_coverage: float
    details: dict[str, str] = field(default_factory=dict)   # per-dimension notes

@dataclass(frozen=True)
class FreshnessReport:
    state: str                         # fresh | aging | stale | unknown
    age_seconds: int
    schema_hash_matches: bool
    permission_version_matches: bool
    refresh_due_at: str | None
```

No single arbitrary score: consumers read dimensions. `state` is derived by explicit thresholds
(see ADR-009); `INSUFFICIENT` blocks guessing consumers.

## 6. Versioning rules

1. A `ContextRecord` version is **immutable** once `ACTIVE`; changes create version+1 with
   `supersedes` pointing at the prior record (auditable history).
2. `schema_hash` changes force `STALE` on all records in the scope; rebuild produces a new version.
3. Artifact `schema_version` (payload shape) is separate from context `version` (data generation);
   both are stored so older payloads remain readable after upgrades.
4. Graph nodes/edges store `context_version` and `schema_hash`; graph queries filter on the ACTIVE
   version, so partially rebuilt graphs never mix generations.
5. `permission_version` participates in retrieval cache keys and governance validity.
