"""TopologyService — structural connectivity: FK edges, inferred joins, join paths.

FK edges come from the catalog (confidence 1.0). Inferred edges use the
`<entity>_id -> <entity>.pk` rule with type-family checks; they are proposals
(INFERRED provenance) with conservative confidence.
"""
from collections import deque
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    JoinEdge,
    ProvenanceSource,
    SchemaContext,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)
from datahek.engine.plan import type_family

ARTIFACT_SCHEMA_VERSION = 1
_INFERRED_BASE_CONFIDENCE = 0.6
_MAX_PATHS_PER_PAIR = 3
_MAX_PATH_DEPTH = 3


def infer_join_edges(schema: SchemaContext) -> tuple[JoinEdge, ...]:
    by_name = {table.name.lower(): table for table in schema.tables}
    fk_columns = {(table.name, column.name)
                  for table in schema.tables for column in table.columns
                  if column.is_foreign_key}
    edges: list[JoinEdge] = []
    for table in schema.tables:
        for column in table.columns:
            if (table.name, column.name) in fk_columns:
                continue
            lowered = column.name.lower()
            if not lowered.endswith("_id"):
                continue
            base = lowered[:-3]
            singular = base[:-1] if base.endswith("s") and not base.endswith("ss") else base
            candidates = [base, f"{base}s", f"{base}es", singular]
            if singular.endswith("y"):
                candidates.append(f"{singular[:-1]}ies")
            target = next((by_name[c] for c in candidates if c in by_name), None)
            if target is None or target.name == table.name:
                continue
            if len(target.primary_key) != 1:
                continue
            target_column = next((c for c in target.columns
                                  if c.name == target.primary_key[0]), None)
            if target_column is None:
                continue
            if type_family(column.data_type) != type_family(target_column.data_type):
                continue
            edges.append(JoinEdge(
                left=f"{table.name}.{column.name}",
                right=f"{target.name}.{target_column.name}",
                kind="inferred",
                cardinality="N:1",
                fanout_risk="low",
                provenance=ProvenanceSource.INFERRED,
                confidence=_INFERRED_BASE_CONFIDENCE,
            ))
    return tuple(edges)


def _edge_ref(edge: JoinEdge) -> str:
    return f"{edge.left}={edge.right}"


def _join_paths(tables: tuple[str, ...], edges: tuple[JoinEdge, ...],
                max_depth: int) -> dict[str, tuple[tuple[str, ...], ...]]:
    adjacency: dict[str, list[tuple[str, JoinEdge]]] = {}
    for edge in edges:
        left_table = edge.left.split(".")[0]
        right_table = edge.right.split(".")[0]
        adjacency.setdefault(left_table, []).append((right_table, edge))
        adjacency.setdefault(right_table, []).append((left_table, edge))

    def find_paths(start: str, goal: str) -> list[tuple[str, ...]]:
        if start == goal:
            return []
        found: list[tuple[str, ...]] = []
        queue: deque[tuple[str, tuple[str, ...], frozenset[str]]] = deque(
            [(start, (), frozenset({start}))])
        while queue and len(found) < _MAX_PATHS_PER_PAIR:
            current, path, visited = queue.popleft()
            if len(path) >= max_depth:
                continue
            for neighbor, edge in sorted(adjacency.get(current, []),
                                         key=lambda item: _edge_ref(item[1])):
                if neighbor in visited:
                    continue
                next_path = path + (_edge_ref(edge),)
                if neighbor == goal:
                    if next_path not in found:
                        found.append(next_path)
                    continue
                queue.append((neighbor, next_path, visited | {neighbor}))
        return found

    paths: dict[str, tuple[tuple[str, ...], ...]] = {}
    for start in tables:
        for goal in tables:
            if start == goal:
                continue
            found = find_paths(start, goal)
            if found:
                paths[f"{start}->{goal}"] = tuple(found)
    return paths


def build_topology_context(schema: SchemaContext, *,
                           max_depth: int = _MAX_PATH_DEPTH) -> TopologyContext:
    edges: list[JoinEdge] = []
    for table in schema.tables:
        for column, reference in table.foreign_keys:
            edges.append(JoinEdge(
                left=f"{table.name}.{column}",
                right=reference,
                kind="fk",
                cardinality="N:1",
                fanout_risk="low",
                provenance=ProvenanceSource.DATABASE,
                confidence=1.0,
            ))
    edges.extend(infer_join_edges(schema))
    edge_tuple = tuple(edges)
    envelope = ArtifactEnvelope(
        kind=ArtifactKind.TOPOLOGY,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        provenance=ProvenanceSource.SYSTEM,
        trust=TrustLevel.STRUCTURAL,
        validation=ValidationStatus.PENDING,
        confidence=1.0,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    return TopologyContext(
        envelope=envelope,
        edges=edge_tuple,
        join_paths=_join_paths(tuple(t.name for t in schema.tables), edge_tuple, max_depth),
    )
