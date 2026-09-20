"""Shared GraphRepository contract — every backend must pass these tests."""
import asyncio
import unittest

from datahek.contracts.context import GraphNode, GraphRelationship, ProvenanceSource
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

STAMP = "2026-09-21T00:00:00Z"


class GraphRepositoryContract(unittest.TestCase):
    """Subclasses implement make_repo() returning a fresh, empty repository."""

    def make_repo(self):  # pragma: no cover
        raise NotImplementedError

    def setUp(self):
        self.repo = self.make_repo()
        self.ctx = RequestContext(source="cli")
        self.other = RequestContext(source="cli", organization_id="other-org")
        asyncio.run(self._setup_schema())

    async def _setup_schema(self):
        init = getattr(self.repo, "init_schema", None)
        if init is not None:
            await init()

    def node(self, node_id, label="Table", org="default", version=1, **props):
        return GraphNode(id=node_id, org_id=org, project_id="default", label=label,
                         properties=props or {"name": node_id}, context_version=version,
                         schema_hash="hash-1", provenance=ProvenanceSource.SYSTEM,
                         created_at=STAMP, updated_at=STAMP)

    def rel(self, rel_id, rel_type, source, target, org="default", version=1):
        return GraphRelationship(id=rel_id, org_id=org, project_id="default",
                                 type=rel_type, source_id=source, target_id=target,
                                 context_version=version, schema_hash="hash-1",
                                 provenance=ProvenanceSource.SYSTEM, confidence=1.0)

    def call(self, coro):
        return asyncio.run(coro)

    def test_create_and_get_node(self):
        self.call(self.repo.create_node(self.ctx, self.node("n1", name="orders")))
        fetched = self.call(self.repo.get_node(self.ctx, "n1"))
        self.assertEqual(fetched.id, "n1")
        self.assertEqual(fetched.properties["name"], "orders")
        self.assertEqual(fetched.label, "Table")
        self.assertEqual(fetched.context_version, 1)

    def test_create_node_is_idempotent_upsert(self):
        self.call(self.repo.create_node(self.ctx, self.node("n1", name="orders")))
        self.call(self.repo.create_node(self.ctx, self.node("n1", name="orders_v2")))
        fetched = self.call(self.repo.get_node(self.ctx, "n1"))
        self.assertEqual(fetched.properties["name"], "orders_v2")
        found = self.call(self.repo.find_nodes(self.ctx, label="Table"))
        self.assertEqual(len([n for n in found if n.id == "n1"]), 1)

    def test_update_missing_node_raises_not_found(self):
        with self.assertRaises(DatahekError) as cm:
            self.call(self.repo.update_node(self.ctx, self.node("missing")))
        self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)

    def test_update_node_changes_properties(self):
        self.call(self.repo.create_node(self.ctx, self.node("n1", name="orders")))
        self.call(self.repo.update_node(self.ctx, self.node("n1", name="orders_new")))
        self.assertEqual(self.call(self.repo.get_node(self.ctx, "n1")).properties["name"],
                         "orders_new")

    def test_find_nodes_filters_label_and_properties(self):
        self.call(self.repo.create_node(self.ctx, self.node("t1", label="Table", name="orders")))
        self.call(self.repo.create_node(self.ctx, self.node("c1", label="Column", name="amount")))
        tables = self.call(self.repo.find_nodes(self.ctx, label="Table"))
        self.assertEqual([n.id for n in tables], ["t1"])
        filtered = self.call(self.repo.find_nodes(self.ctx, label="Column",
                                                 where={"name": "amount"}))
        self.assertEqual([n.id for n in filtered], ["c1"])

    def test_tenant_isolation(self):
        self.call(self.repo.create_node(self.ctx, self.node("n1")))
        self.assertIsNone(self.call(self.repo.get_node(self.other, "n1")))
        self.assertEqual(self.call(self.repo.find_nodes(self.other, label="Table")), [])

    def test_relationships_traversal_and_filter(self):
        self.call(self.repo.create_node(self.ctx, self.node("a", label="Table")))
        self.call(self.repo.create_node(self.ctx, self.node("b", label="Column")))
        self.call(self.repo.create_node(self.ctx, self.node("c", label="Metric")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r1", "HAS_COLUMN", "a", "b")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r2", "HAS_METRIC", "a", "c")))
        neighbors = self.call(self.repo.neighbors(self.ctx, "a"))
        self.assertEqual({n.id for n in neighbors}, {"b", "c"})
        only_columns = self.call(self.repo.neighbors(self.ctx, "a", rel_type="HAS_COLUMN"))
        self.assertEqual([n.id for n in only_columns], ["b"])

    def test_depth_two_traversal(self):
        for node_id in ("a", "b", "c"):
            self.call(self.repo.create_node(self.ctx, self.node(node_id)))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r1", "HAS_COLUMN", "a", "b")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r2", "HAS_COLUMN", "b", "c")))
        two_hop = self.call(self.repo.neighbors(self.ctx, "a", depth=2))
        self.assertEqual({n.id for n in two_hop}, {"b", "c"})

    def test_paths_between_nodes(self):
        for node_id in ("a", "b", "c"):
            self.call(self.repo.create_node(self.ctx, self.node(node_id)))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r1", "HAS_COLUMN", "a", "b")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r2", "HAS_COLUMN", "b", "c")))
        paths = self.call(self.repo.paths(self.ctx, from_id="a", to_id="c", max_depth=3))
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].length, 2)
        self.assertEqual([n.id for n in paths[0].nodes], ["a", "b", "c"])
        self.assertEqual(self.call(self.repo.paths(self.ctx, from_id="a", to_id="c",
                                                  max_depth=1)), [])

    def test_delete_node_removes_relationships(self):
        self.call(self.repo.create_node(self.ctx, self.node("a")))
        self.call(self.repo.create_node(self.ctx, self.node("b")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r1", "HAS_COLUMN", "a", "b")))
        self.call(self.repo.delete_node(self.ctx, "b"))
        self.assertIsNone(self.call(self.repo.get_node(self.ctx, "b")))
        self.assertEqual(self.call(self.repo.neighbors(self.ctx, "a")), [])

    def test_delete_relationship_is_idempotent(self):
        self.call(self.repo.create_node(self.ctx, self.node("a")))
        self.call(self.repo.create_node(self.ctx, self.node("b")))
        self.call(self.repo.create_relationship(self.ctx, self.rel("r1", "HAS_COLUMN", "a", "b")))
        self.call(self.repo.delete_relationship(self.ctx, "r1"))
        self.assertEqual(self.call(self.repo.neighbors(self.ctx, "a")), [])
        self.call(self.repo.delete_relationship(self.ctx, "r1"))

    def test_unknown_relationship_type_rejected(self):
        self.call(self.repo.create_node(self.ctx, self.node("a")))
        self.call(self.repo.create_node(self.ctx, self.node("b")))
        with self.assertRaises(DatahekError) as cm:
            self.call(self.repo.create_relationship(
                self.ctx, self.rel("r1", "DROP_EVERYTHING", "a", "b")))
        self.assertEqual(cm.exception.code, ErrorCode.VALIDATION)

    def test_health_check(self):
        self.assertTrue(self.call(self.repo.health_check()))
