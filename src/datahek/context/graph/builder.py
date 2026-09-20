"""SchemaGraphBuilder — project context artifacts into the Schema Knowledge Graph (ADR-003).

Stable node ids make rebuilds idempotent; per-connection nodes that are no longer
part of the current context are pruned; an unavailable graph backend produces a
DEGRADED report instead of failing the build (ADR-009, FR-009, ADR-011).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from datahek.contracts.context import (
    GraphNode,
    GraphRelationship,
    OntologyContext,
    ProfileContext,
    ProvenanceSource,
    SchemaContext,
    TaxonomyContext,
    TopologyContext,
)
from datahek.kernel.context import RequestContext

_LABELS = ("Connection", "Table", "Column", "Metric", "Concept")


@dataclass(frozen=True)
class GraphBuildReport:
    connection_id: str
    context_version: int
    nodes_written: int
    relationships_written: int
    nodes_pruned: int
    degraded: bool = False
    warnings: tuple[str, ...] = ()


def _text(value) -> str:
    return "" if value is None else str(value)


class SchemaGraphBuilder:
    def __init__(self, repository):
        self._repo = repository

    async def build(self, ctx: RequestContext, connection_id: str, *,
                    schema: SchemaContext,
                    profiles: ProfileContext | None = None,
                    topology: TopologyContext | None = None,
                    taxonomy: TaxonomyContext | None = None,
                    granularity=None,
                    ontology: OntologyContext | None = None,
                    metrics: tuple[dict, ...] = (),
                    context_version: int = 1,
                    generated_at: str | None = None) -> GraphBuildReport:
        if self._repo is None or not await self._repo.health_check():
            return GraphBuildReport(
                connection_id=connection_id, context_version=context_version,
                nodes_written=0, relationships_written=0, nodes_pruned=0,
                degraded=True, warnings=("graph backend unavailable",))

        stamp = generated_at or datetime.now(timezone.utc).isoformat()
        nodes: dict[str, GraphNode] = {}
        relationships: list[GraphRelationship] = []

        def make_node(node_id: str, label: str, provenance: ProvenanceSource, **props) -> GraphNode:
            properties = {"connection_id": connection_id}
            properties.update({key: _text(value) for key, value in props.items()})
            return GraphNode(
                id=node_id, org_id=ctx.organization_id, project_id=ctx.project_id,
                label=label, properties=properties, context_version=context_version,
                schema_hash=schema.schema_hash, provenance=provenance,
                created_at=stamp, updated_at=stamp)

        def make_rel(rel_id: str, rel_type: str, source_id: str, target_id: str,
                     provenance: ProvenanceSource, confidence: float, **props) -> GraphRelationship:
            return GraphRelationship(
                id=rel_id, org_id=ctx.organization_id, project_id=ctx.project_id,
                type=rel_type, source_id=source_id, target_id=target_id,
                context_version=context_version, schema_hash=schema.schema_hash,
                provenance=provenance, confidence=confidence,
                properties={key: _text(value) for key, value in props.items()})

        connection_node_id = f"connection:{connection_id}"
        nodes[connection_node_id] = make_node(
            connection_node_id, "Connection", ProvenanceSource.SYSTEM, name=connection_id)

        role_by_member = {}
        profile_rows = {}
        if profiles is not None:
            for table_name, column_profiles in profiles.tables.items():
                if column_profiles:
                    profile_rows[table_name] = column_profiles[0].row_count
                for column_profile in column_profiles:
                    role_by_member[f"{table_name}.{column_profile.name}"] = column_profile

        category_by_member = {}
        if taxonomy is not None:
            for taxonomy_node in taxonomy.nodes:
                if taxonomy_node.node_kind == "category":
                    for member in taxonomy_node.members:
                        category_by_member[member] = taxonomy_node.path[-1]

        grain_by_table = {}
        if granularity is not None:
            for grain in granularity.grains:
                grain_by_table[grain.table] = grain

        metrics_by_table: dict[str, list[dict]] = {}
        for metric in metrics:
            metrics_by_table.setdefault(str(metric.get("table", "")), []).append(metric)

        for table in schema.tables:
            table_node_id = f"table:{connection_id}:{table.name}"
            grain = grain_by_table.get(table.name)
            nodes[table_node_id] = make_node(
                table_node_id, "Table", ProvenanceSource.DATABASE,
                name=table.name,
                row_count=profile_rows.get(table.name, table.estimated_rows),
                grain=grain.statement if grain else "",
                grain_confidence="" if grain is None else f"{grain.confidence:.2f}")
            relationships.append(make_rel(
                f"rel:HAS_TABLE:{connection_node_id}->{table_node_id}", "HAS_TABLE",
                connection_node_id, table_node_id, ProvenanceSource.DATABASE, 1.0))

            for column in table.columns:
                member = f"{table.name}.{column.name}"
                column_node_id = f"column:{connection_id}:{member}"
                column_profile = role_by_member.get(member)
                nodes[column_node_id] = make_node(
                    column_node_id, "Column", ProvenanceSource.DATABASE,
                    name=column.name,
                    data_type=column.data_type,
                    nullable=column.nullable,
                    is_primary_key=column.is_primary_key,
                    is_foreign_key=column.is_foreign_key,
                    references=column.references or "",
                    null_ratio="" if column_profile is None else f"{column_profile.null_ratio:.4f}",
                    distinct_count="" if column_profile is None else column_profile.distinct_count,
                    uniqueness_ratio="" if column_profile is None or column_profile.uniqueness_ratio is None
                    else f"{column_profile.uniqueness_ratio:.4f}",
                    roles="" if column_profile is None else ",".join(column_profile.role_candidates),
                    sensitive="" if column_profile is None else column_profile.sensitive,
                    taxonomy_category=category_by_member.get(member, ""))
                relationships.append(make_rel(
                    f"rel:HAS_COLUMN:{table_node_id}->{column_node_id}", "HAS_COLUMN",
                    table_node_id, column_node_id, ProvenanceSource.DATABASE, 1.0))

        if topology is not None:
            for edge in topology.edges:
                source_id = f"column:{connection_id}:{edge.left}"
                target_id = f"column:{connection_id}:{edge.right}"
                if source_id not in nodes or target_id not in nodes or source_id == target_id:
                    continue
                rel_type = "REFERENCES" if edge.kind == "fk" else "JOINS_WITH"
                relationships.append(make_rel(
                    f"rel:{rel_type}:{source_id}->{target_id}", rel_type,
                    source_id, target_id, edge.provenance, edge.confidence,
                    kind=edge.kind, cardinality=edge.cardinality,
                    fanout_risk=edge.fanout_risk))

        for table_name, table_metrics in metrics_by_table.items():
            table_node_id = f"table:{connection_id}:{table_name}"
            if table_node_id not in nodes:
                continue
            for metric in table_metrics:
                metric_node_id = f"metric:{connection_id}:{metric.get('name', '')}"
                nodes[metric_node_id] = make_node(
                    metric_node_id, "Metric", ProvenanceSource.SYSTEM,
                    name=metric.get("name", ""), table=table_name,
                    aggregate=metric.get("aggregate", ""), column=metric.get("column", ""),
                    filter=metric.get("filter") or "", description=metric.get("description", ""))
                relationships.append(make_rel(
                    f"rel:HAS_METRIC:{table_node_id}->{metric_node_id}", "HAS_METRIC",
                    table_node_id, metric_node_id, ProvenanceSource.SYSTEM, 1.0))

        if ontology is not None:
            concept_ids = {}
            for concept in ontology.concepts:
                concept_node_id = f"concept:{connection_id}:{concept.name}"
                concept_ids[concept.name] = concept_node_id
                nodes[concept_node_id] = make_node(
                    concept_node_id, "Concept", ProvenanceSource.LLM,
                    name=concept.name, kind=concept.kind, description=concept.description,
                    synonyms=",".join(concept.synonyms),
                    validation=concept.validation.value)
                for table_name in concept.maps_to:
                    table_node_id = f"table:{connection_id}:{table_name}"
                    if table_node_id in nodes:
                        relationships.append(make_rel(
                            f"rel:DESCRIBES:{concept_node_id}->{table_node_id}", "DESCRIBES",
                            concept_node_id, table_node_id, ProvenanceSource.LLM,
                            concept.confidence))
            for relationship in ontology.relationships:
                source_id = concept_ids.get(relationship.subject)
                target_id = concept_ids.get(relationship.object)
                if source_id is None or target_id is None:
                    continue
                relationships.append(make_rel(
                    f"rel:SEMANTICALLY_RELATED_TO:{source_id}->{target_id}:{relationship.kind}",
                    "SEMANTICALLY_RELATED_TO", source_id, target_id,
                    ProvenanceSource.LLM, relationship.confidence,
                    kind=relationship.kind, predicate=relationship.predicate))

        for graph_node in nodes.values():
            await self._repo.create_node(ctx, graph_node)
        for relationship in relationships:
            await self._repo.create_relationship(ctx, relationship)

        pruned = 0
        for label in _LABELS:
            existing = await self._repo.find_nodes(
                ctx, label=label, where={"connection_id": connection_id}, limit=1000)
            for existing_node in existing:
                if existing_node.id not in nodes:
                    await self._repo.delete_node(ctx, existing_node.id)
                    pruned += 1

        return GraphBuildReport(
            connection_id=connection_id, context_version=context_version,
            nodes_written=len(nodes), relationships_written=len(relationships),
            nodes_pruned=pruned)
