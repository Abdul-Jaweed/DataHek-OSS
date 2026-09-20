"""InMemoryGraphRepository — deterministic adapter for tests and graph-less mode."""
from collections import deque

from datahek.contracts.context import GraphNode, GraphPath, GraphRelationship
from datahek.context.graph.vocabulary import assert_relationship_type
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_MAX_PATHS = 10


class InMemoryGraphRepository:
    def __init__(self):
        self._nodes: dict[str, GraphNode] = {}
        self._rels: dict[str, GraphRelationship] = {}

    async def create_node(self, ctx: RequestContext, node: GraphNode) -> str:
        self._nodes[node.id] = node
        return node.id

    async def update_node(self, ctx: RequestContext, node: GraphNode) -> None:
        existing = self._nodes.get(node.id)
        if existing is None or existing.org_id != ctx.organization_id:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Graph node '{node.id}' not found")
        self._nodes[node.id] = node

    async def delete_node(self, ctx: RequestContext, node_id: str) -> None:
        node = self._nodes.get(node_id)
        if node is None or node.org_id != ctx.organization_id:
            return
        del self._nodes[node_id]
        self._rels = {rel_id: rel for rel_id, rel in self._rels.items()
                      if rel.source_id != node_id and rel.target_id != node_id}

    async def get_node(self, ctx: RequestContext, node_id: str) -> GraphNode | None:
        node = self._nodes.get(node_id)
        if node is None or node.org_id != ctx.organization_id:
            return None
        return node

    async def find_nodes(self, ctx: RequestContext, *, label: str,
                         where: dict | None = None, limit: int = 100) -> list[GraphNode]:
        matches = []
        for node in self._nodes.values():
            if node.org_id != ctx.organization_id or node.label != label:
                continue
            if where and any(node.properties.get(k) != v for k, v in where.items()):
                continue
            matches.append(node)
        return sorted(matches, key=lambda n: n.id)[:limit]

    async def create_relationship(self, ctx: RequestContext,
                                  rel: GraphRelationship) -> str:
        assert_relationship_type(rel.type)
        source = await self.get_node(ctx, rel.source_id)
        target = await self.get_node(ctx, rel.target_id)
        if source is None or target is None:
            raise DatahekError(ErrorCode.NOT_FOUND,
                               "Graph relationship endpoints not found")
        self._rels[rel.id] = rel
        return rel.id

    async def delete_relationship(self, ctx: RequestContext, rel_id: str) -> None:
        rel = self._rels.get(rel_id)
        if rel is not None and rel.org_id == ctx.organization_id:
            del self._rels[rel_id]

    async def neighbors(self, ctx: RequestContext, node_id: str, *,
                        rel_type: str | None = None, depth: int = 1) -> list[GraphNode]:
        if rel_type is not None:
            assert_relationship_type(rel_type)
        start = await self.get_node(ctx, node_id)
        if start is None:
            return []
        seen: dict[str, GraphNode] = {}
        frontier = {node_id}
        for _ in range(max(1, depth)):
            next_frontier: set[str] = set()
            for rel in self._rels.values():
                if rel.org_id != ctx.organization_id:
                    continue
                if rel_type is not None and rel.type != rel_type:
                    continue
                if rel.source_id in frontier:
                    next_frontier.add(rel.target_id)
                elif rel.target_id in frontier:
                    next_frontier.add(rel.source_id)
            for candidate in next_frontier:
                if candidate == node_id or candidate in seen:
                    continue
                node = await self.get_node(ctx, candidate)
                if node is not None:
                    seen[candidate] = node
            frontier = next_frontier
        return sorted(seen.values(), key=lambda n: n.id)

    async def paths(self, ctx: RequestContext, *, from_id: str, to_id: str,
                    max_depth: int = 3,
                    rel_types: list[str] | None = None) -> list[GraphPath]:
        if rel_types:
            for rel_type in rel_types:
                assert_relationship_type(rel_type)
        if await self.get_node(ctx, from_id) is None:
            return []
        adjacency: dict[str, list[tuple[str, GraphRelationship]]] = {}
        for rel in self._rels.values():
            if rel.org_id != ctx.organization_id:
                continue
            if rel_types and rel.type not in rel_types:
                continue
            adjacency.setdefault(rel.source_id, []).append((rel.target_id, rel))
            adjacency.setdefault(rel.target_id, []).append((rel.source_id, rel))
        results: list[GraphPath] = []
        queue: deque[tuple[str, list[GraphRelationship], set[str]]] = deque(
            [(from_id, [], {from_id})])
        while queue and len(results) < _MAX_PATHS:
            current, rels, visited = queue.popleft()
            if len(rels) >= max_depth:
                continue
            for neighbor, rel in sorted(adjacency.get(current, []),
                                        key=lambda item: item[0] + item[1].id):
                if neighbor in visited:
                    continue
                next_rels = rels + [rel]
                if neighbor == to_id:
                    chain = [await self.get_node(ctx, from_id)]
                    for relationship in next_rels:
                        previous = chain[-1].id
                        next_id = (relationship.target_id
                                   if relationship.source_id == previous
                                   else relationship.source_id)
                        chain.append(await self.get_node(ctx, next_id))
                    results.append(GraphPath(nodes=tuple(chain),
                                             relationships=tuple(next_rels),
                                             length=len(next_rels)))
                    continue
                queue.append((neighbor, next_rels, visited | {neighbor}))
        return results

    async def health_check(self) -> bool:
        return True
