"""ContextRetriever — select the slices relevant to a question (FR-012).

Deterministic token overlap against table/column/metric/concept text; no LLM.
Always bounded (table and column caps) — never the whole store or graph. Stale
context is returned with ``stale=True`` so callers can warn and queue a rebuild.
"""
import asyncio
import re

from datahek.contracts.context import (
    ArtifactKind,
    ContextArtifact,
    GovernanceContext,
    GranularityContext,
    OntologyContext,
    ProfileContext,
    RetrievedContext,
    SchemaContext,
    TaxonomyContext,
    TopologyContext,
)
from datahek.kernel.context import RequestContext

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "by", "in", "on", "to", "and", "or", "with",
    "per", "how", "many", "what", "which", "show", "me", "top", "last", "this",
    "that", "from", "as", "is", "are", "was", "were", "be", "all", "each",
    "between", "over", "past", "count", "average", "avg", "total", "sum",
    "number", "please", "give", "list", "using", "where",
})
_TABLE_CAP = 8
_COLUMN_CAP = 40


def question_tokens(question: str) -> frozenset[str]:
    return frozenset(token for token in _TOKEN.findall(question.lower())
                     if token not in _STOPWORDS and len(token) > 1)


def _overlap(text: str, tokens: frozenset[str]) -> int:
    return sum(1 for part in _TOKEN.findall(text.lower()) if part in tokens)


class ContextRetrieverService:
    def __init__(self, registry, store, semantic_store=None):
        self._registry = registry
        self._store = store
        self._semantic_store = semantic_store

    async def retrieve(self, ctx: RequestContext, *, connection_id: str, question: str,
                       scope: str = "connection",
                       current_schema_hash: str | None = None) -> RetrievedContext | None:
        active = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        if active is None:
            return None
        artifacts: dict[ArtifactKind, ContextArtifact] = {}
        kinds = list(active.artifact_kinds)
        if kinds:
            loaded = await asyncio.gather(
                *(self._store.get(ctx, active.context_id, kind) for kind in kinds))
            artifacts = {kind: artifact
                         for kind, artifact in zip(kinds, loaded) if artifact is not None}
        schema = artifacts.get(ArtifactKind.SCHEMA)
        if not isinstance(schema, SchemaContext):
            return None

        tokens = question_tokens(question)
        metrics = await self._load_metrics(ctx)
        selected_tables = self._select_tables(schema, artifacts, metrics, tokens)
        selected_names = {table.name for table in selected_tables}
        columns_by_table = {
            table.name: self._select_columns(table, tokens) for table in selected_tables
        }

        profiles: dict[str, tuple] = {}
        profile_artifact = artifacts.get(ArtifactKind.PROFILE)
        if isinstance(profile_artifact, ProfileContext):
            for name in selected_names:
                if name in profile_artifact.tables:
                    wanted = set(columns_by_table.get(name, ()))
                    profiles[name] = tuple(
                        profile for profile in profile_artifact.tables[name]
                        if not wanted or profile.name in wanted)

        topology = artifacts.get(ArtifactKind.TOPOLOGY)
        if isinstance(topology, TopologyContext):
            topology = self._filter_topology(topology, selected_names)

        granularity = artifacts.get(ArtifactKind.GRANULARITY)
        if isinstance(granularity, GranularityContext):
            kept_metrics = {str(m.get("name", "")) for m in metrics}
            granularity = GranularityContext(
                envelope=granularity.envelope,
                grains=tuple(grain for grain in granularity.grains
                             if grain.table in selected_names),
                metric_grains=tuple(mg for mg in granularity.metric_grains
                                    if mg.metric in kept_metrics))

        taxonomy = artifacts.get(ArtifactKind.TAXONOMY)
        if isinstance(taxonomy, TaxonomyContext):
            taxonomy = TaxonomyContext(
                envelope=taxonomy.envelope,
                nodes=tuple(node for node in taxonomy.nodes
                            if self._node_touches(node, selected_names)))

        ontology = artifacts.get(ArtifactKind.ONTOLOGY)
        if isinstance(ontology, OntologyContext):
            ontology = self._filter_ontology(ontology, selected_names)

        governance = artifacts.get(ArtifactKind.GOVERNANCE)
        if not isinstance(governance, GovernanceContext):
            governance = None

        stale = (current_schema_hash is not None
                 and current_schema_hash != active.schema_hash)
        return RetrievedContext(
            context_id=active.context_id, version=active.version,
            schema_hash=active.schema_hash, scope=scope, connection_id=connection_id,
            schema=tuple(selected_tables), profiles=profiles, topology=topology,
            granularity=granularity, taxonomy=taxonomy, ontology=ontology,
            governance=governance, metrics=metrics, quality=active.quality,
            freshness=active.freshness, stale=stale)

    async def _load_metrics(self, ctx: RequestContext) -> tuple[dict, ...]:
        if self._semantic_store is None:
            return ()
        try:
            metrics = await self._semantic_store.list(ctx)
        except Exception:
            return ()
        return tuple(sorted((dict(metric) for metric in metrics),
                            key=lambda metric: str(metric.get("name", ""))))

    @staticmethod
    def _select_tables(schema: SchemaContext, artifacts, metrics, tokens) -> list:
        def table_score(table) -> int:
            score = 3 * _overlap(table.name, tokens)
            if any(_overlap(column.name, tokens) for column in table.columns):
                score += 2
            score += _overlap(table.name.replace("_", " "), tokens)
            return score

        scores = {table.name: table_score(table) for table in schema.tables}
        taxonomy = artifacts.get(ArtifactKind.TAXONOMY)
        if isinstance(taxonomy, TaxonomyContext):
            for node in taxonomy.nodes:
                for member in node.members:
                    table_name = member.split(".")[0]
                    if table_name in scores:
                        scores[table_name] += _overlap(" ".join(node.path), tokens)
        ontology = artifacts.get(ArtifactKind.ONTOLOGY)
        if isinstance(ontology, OntologyContext):
            for concept in ontology.concepts:
                concept_score = (_overlap(concept.name, tokens)
                                 + _overlap(concept.description, tokens)
                                 + _overlap(" ".join(concept.synonyms), tokens))
                for table_name in concept.maps_to:
                    if table_name in scores:
                        scores[table_name] += 2 * concept_score
        for metric in metrics:
            table_name = str(metric.get("table", ""))
            if table_name in scores:
                metric_score = (_overlap(str(metric.get("name", "")), tokens)
                                + _overlap(str(metric.get("description", "")), tokens))
                scores[table_name] += 3 * metric_score

        ranked = sorted(schema.tables, key=lambda table: (-scores[table.name], table.name))
        matched = [table for table in ranked if scores[table.name] > 0]
        chosen = matched or ranked
        return chosen[:_TABLE_CAP]

    @staticmethod
    def _select_columns(table, tokens) -> tuple[str, ...]:
        if len(table.columns) <= _COLUMN_CAP:
            return tuple(column.name for column in table.columns)
        matched = [column for column in table.columns if _overlap(column.name, tokens)]
        remaining = sorted(
            (column for column in table.columns if column not in matched),
            key=lambda column: (not column.is_primary_key, not column.is_foreign_key,
                                column.ordinal))
        ordered = matched + remaining
        return tuple(column.name for column in ordered[:_COLUMN_CAP])

    @staticmethod
    def _filter_topology(topology: TopologyContext, selected: set[str]) -> TopologyContext:
        edges = tuple(edge for edge in topology.edges
                      if edge.left.split(".")[0] in selected
                      and edge.right.split(".")[0] in selected)
        paths = {key: value for key, value in topology.join_paths.items()
                 if key.split("->")[0] in selected and key.split("->")[-1] in selected}
        return TopologyContext(envelope=topology.envelope, edges=edges, join_paths=paths)

    @staticmethod
    def _node_touches(node, selected: set[str]) -> bool:
        return any(member.split(".")[0] in selected for member in node.members) \
            or any(part in selected for part in node.path)

    @staticmethod
    def _filter_ontology(ontology: OntologyContext, selected: set[str]) -> OntologyContext:
        concepts = tuple(concept for concept in ontology.concepts
                         if any(table in selected for table in concept.maps_to))
        names = {concept.name for concept in concepts}
        relationships = tuple(relationship for relationship in ontology.relationships
                              if relationship.subject in names
                              and relationship.object in names)
        return OntologyContext(envelope=ontology.envelope, concepts=concepts,
                               relationships=relationships)
