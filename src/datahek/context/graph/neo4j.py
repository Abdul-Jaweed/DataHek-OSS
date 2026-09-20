"""Neo4jGraphRepository — the only module that speaks Cypher (ADR-005).

Nodes use a single label with prefixed properties so no dynamic labels or
property-name interpolation are needed. Relationship types come from the closed
vocabulary and are validated before interpolation; numeric bounds are int-cast.
Reads are tenant-scoped (ADR-012); MERGE on stable ids keeps rebuilds idempotent.
"""
import re

from datahek.contracts.context import (
    GraphNode,
    GraphPath,
    GraphRelationship,
    ProvenanceSource,
)
from datahek.context.graph.vocabulary import assert_relationship_type
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

NODE_LABEL = "DataHekNode"
_PROP_PREFIX = "p_"
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
_CONSTRAINTS = (
    f"CREATE CONSTRAINT datahek_node_id IF NOT EXISTS FOR (n:{NODE_LABEL}) REQUIRE n.id IS UNIQUE",
    f"CREATE INDEX datahek_node_org IF NOT EXISTS FOR (n:{NODE_LABEL}) ON (n.org_id)",
    f"CREATE INDEX datahek_node_label IF NOT EXISTS "
    f"FOR (n:{NODE_LABEL}) ON (n.org_id, n.label)",
)
_MAX_PATHS = 10


def _assert_property_key(key: str) -> str:
    if not _KEY_PATTERN.match(key):
        raise DatahekError(ErrorCode.VALIDATION,
                           f"Invalid graph property name '{key}'")
    return key


class Neo4jGraphRepository:
    def __init__(self, url: str, user: str = "neo4j", password: str = "",
                 database: str | None = None):
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:
            raise DatahekError(
                ErrorCode.VALIDATION,
                "Neo4j driver is not installed (install datahek-core[graph])") from exc
        self._driver = AsyncGraphDatabase.driver(url, auth=(user, password))
        self._database = database

    @classmethod
    def from_env(cls) -> "Neo4jGraphRepository":
        import os

        return cls(
            url=os.environ["DATAHEK_NEO4J_URL"],
            user=os.environ.get("DATAHEK_NEO4J_USER", "neo4j"),
            password=os.environ.get("DATAHEK_NEO4J_PASSWORD", ""),
            database=os.environ.get("DATAHEK_NEO4J_DATABASE") or None,
        )

    def _session(self):
        return self._driver.session(database=self._database)

    async def init_schema(self) -> None:
        async with self._session() as session:
            for statement in _CONSTRAINTS:
                await (await session.run(statement)).consume()

    async def close(self) -> None:
        await self._driver.close()

    @staticmethod
    def _node_props(node: GraphNode) -> dict:
        props = {
            "label": node.label,
            "org_id": node.org_id,
            "project_id": node.project_id,
            "context_version": int(node.context_version),
            "schema_hash": node.schema_hash,
            "provenance": node.provenance.value,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
        }
        for key, value in node.properties.items():
            props[f"{_PROP_PREFIX}{_assert_property_key(key)}"] = (
                "" if value is None else str(value))
        return props

    @staticmethod
    def _to_node(record_node) -> GraphNode:
        props = dict(record_node)
        user_props = {key[len(_PROP_PREFIX):]: value for key, value in props.items()
                      if key.startswith(_PROP_PREFIX)}
        return GraphNode(
            id=props["id"],
            org_id=props.get("org_id", ""),
            project_id=props.get("project_id", ""),
            label=props.get("label", ""),
            properties=user_props,
            context_version=int(props.get("context_version", 0)),
            schema_hash=props.get("schema_hash", ""),
            provenance=ProvenanceSource(props.get("provenance", "system")),
            created_at=props.get("created_at", ""),
            updated_at=props.get("updated_at", ""),
        )

    @staticmethod
    def _endpoint_id(node) -> str:
        if hasattr(node, "get"):
            value = node.get("id")
            if value is not None:
                return str(value)
        return str(getattr(node, "element_id", ""))

    @classmethod
    def _to_relationship(cls, record_rel) -> GraphRelationship:
        props = dict(record_rel)
        user_props = {key[len(_PROP_PREFIX):]: value for key, value in props.items()
                      if key.startswith(_PROP_PREFIX)}
        return GraphRelationship(
            id=props.get("id", ""),
            org_id=props.get("org_id", ""),
            project_id=props.get("project_id", ""),
            type=record_rel.type,
            source_id=cls._endpoint_id(record_rel.start_node),
            target_id=cls._endpoint_id(record_rel.end_node),
            context_version=int(props.get("context_version", 0)),
            schema_hash=props.get("schema_hash", ""),
            provenance=ProvenanceSource(props.get("provenance", "system")),
            confidence=float(props.get("confidence", 1.0)),
            properties=user_props,
        )

    async def create_node(self, ctx: RequestContext, node: GraphNode) -> str:
        async with self._session() as session:
            result = await session.run(
                f"MERGE (n:{NODE_LABEL} {{id: $id}}) SET n += $props RETURN n.id AS id",
                id=node.id, props=self._node_props(node))
            record = await result.single()
        if record is None:
            raise DatahekError(ErrorCode.CONNECTION_FAILED,
                               "Neo4j did not acknowledge the node write")
        return str(record["id"])

    async def update_node(self, ctx: RequestContext, node: GraphNode) -> None:
        async with self._session() as session:
            result = await session.run(
                f"MATCH (n:{NODE_LABEL} {{id: $id}}) WHERE n.org_id = $org "
                f"SET n += $props RETURN n.id AS id",
                id=node.id, org=ctx.organization_id, props=self._node_props(node))
            record = await result.single()
        if record is None:
            raise DatahekError(ErrorCode.NOT_FOUND,
                               f"Graph node '{node.id}' not found")

    async def delete_node(self, ctx: RequestContext, node_id: str) -> None:
        async with self._session() as session:
            await (await session.run(
                f"MATCH (n:{NODE_LABEL} {{id: $id}}) WHERE n.org_id = $org "
                f"DETACH DELETE n",
                id=node_id, org=ctx.organization_id)).consume()

    async def get_node(self, ctx: RequestContext, node_id: str) -> GraphNode | None:
        async with self._session() as session:
            result = await session.run(
                f"MATCH (n:{NODE_LABEL} {{id: $id}}) WHERE n.org_id = $org RETURN n",
                id=node_id, org=ctx.organization_id)
            record = await result.single()
        return self._to_node(record["n"]) if record else None

    async def find_nodes(self, ctx: RequestContext, *, label: str,
                         where: dict | None = None, limit: int = 100) -> list[GraphNode]:
        conditions = ["n.org_id = $org", "n.label = $label"]
        params: dict = {"org": ctx.organization_id, "label": label,
                        "limit": max(1, min(int(limit), 1000))}
        for index, (key, value) in enumerate((where or {}).items()):
            param = f"w{index}"
            conditions.append(f"n.{_PROP_PREFIX}{_assert_property_key(key)} = ${param}")
            params[param] = "" if value is None else str(value)
        query = (f"MATCH (n:{NODE_LABEL}) WHERE {' AND '.join(conditions)} "
                 f"RETURN n ORDER BY n.id LIMIT $limit")
        nodes: list[GraphNode] = []
        async with self._session() as session:
            result = await session.run(query, **params)
            async for record in result:
                nodes.append(self._to_node(record["n"]))
        return nodes

    async def create_relationship(self, ctx: RequestContext,
                                  rel: GraphRelationship) -> str:
        assert_relationship_type(rel.type)
        props = {
            "id": rel.id,
            "org_id": rel.org_id,
            "project_id": rel.project_id,
            "context_version": int(rel.context_version),
            "schema_hash": rel.schema_hash,
            "provenance": rel.provenance.value,
            "confidence": float(rel.confidence),
        }
        for key, value in rel.properties.items():
            props[f"{_PROP_PREFIX}{_assert_property_key(key)}"] = (
                "" if value is None else str(value))
        async with self._session() as session:
            result = await session.run(
                f"MATCH (a:{NODE_LABEL} {{id: $src}}), (b:{NODE_LABEL} {{id: $dst}}) "
                f"WHERE a.org_id = $org AND b.org_id = $org "
                f"MERGE (a)-[r:{rel.type} {{id: $id}}]->(b) SET r += $props "
                f"RETURN r.id AS id",
                src=rel.source_id, dst=rel.target_id, org=ctx.organization_id,
                id=rel.id, props=props)
            record = await result.single()
        if record is None:
            raise DatahekError(ErrorCode.NOT_FOUND,
                               "Graph relationship endpoints not found")
        return str(record["id"])

    async def delete_relationship(self, ctx: RequestContext, rel_id: str) -> None:
        async with self._session() as session:
            await (await session.run(
                "MATCH ()-[r]->() WHERE r.id = $id AND r.org_id = $org DELETE r",
                id=rel_id, org=ctx.organization_id)).consume()

    async def neighbors(self, ctx: RequestContext, node_id: str, *,
                        rel_type: str | None = None, depth: int = 1) -> list[GraphNode]:
        if rel_type is not None:
            assert_relationship_type(rel_type)
        bounded = max(1, min(int(depth), 5))
        type_pattern = f":{rel_type}" if rel_type else ""
        query = (
            f"MATCH (n:{NODE_LABEL} {{id: $id}})-[r{type_pattern}*1..{bounded}]-"
            f"(m:{NODE_LABEL}) "
            f"WHERE n.org_id = $org AND m.org_id = $org AND m.id <> $id "
            f"RETURN DISTINCT m ORDER BY m.id")
        nodes: list[GraphNode] = []
        async with self._session() as session:
            result = await session.run(query, id=node_id, org=ctx.organization_id)
            async for record in result:
                nodes.append(self._to_node(record["m"]))
        return nodes

    async def paths(self, ctx: RequestContext, *, from_id: str, to_id: str,
                    max_depth: int = 3,
                    rel_types: list[str] | None = None) -> list[GraphPath]:
        if rel_types:
            for rel_type in rel_types:
                assert_relationship_type(rel_type)
            type_pattern = ":" + "|".join(rel_types)
        else:
            type_pattern = ""
        bounded = max(1, min(int(max_depth), 5))
        query = (
            f"MATCH p = allShortestPaths((a:{NODE_LABEL} {{id: $from_id}})"
            f"-[{type_pattern}*1..{bounded}]-(b:{NODE_LABEL} {{id: $to_id}})) "
            f"WHERE a.org_id = $org AND b.org_id = $org "
            f"RETURN p LIMIT $limit")
        paths: list[GraphPath] = []
        async with self._session() as session:
            result = await session.run(query, from_id=from_id, to_id=to_id,
                                       org=ctx.organization_id, limit=_MAX_PATHS)
            async for record in result:
                path = record["p"]
                relationships = tuple(self._to_relationship(rel)
                                      for rel in path.relationships)
                paths.append(GraphPath(
                    nodes=tuple(self._to_node(node) for node in path.nodes),
                    relationships=relationships,
                    length=len(relationships),
                ))
        return paths

    async def health_check(self) -> bool:
        try:
            async with self._session() as session:
                result = await session.run("RETURN 1 AS ok")
                await result.consume()
            return True
        except Exception:
            return False
