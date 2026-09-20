"""Neo4jGraphRepository — contract suite against a live server when configured."""
import os
import unittest

try:
    import graph_repository_contract as contract
except ImportError:  # pragma: no cover - module-path invocation
    from tests import graph_repository_contract as contract

NEO4J_URL = os.environ.get("DATAHEK_TEST_NEO4J_URL")
try:
    import neo4j  # noqa: F401

    HAS_DRIVER = True
except ImportError:
    HAS_DRIVER = False


@unittest.skipUnless(NEO4J_URL, "DATAHEK_TEST_NEO4J_URL not set")
@unittest.skipUnless(HAS_DRIVER, "neo4j driver not installed")
class TestNeo4jGraph(contract.GraphRepositoryContract):
    def make_repo(self):
        from datahek.context.graph.neo4j import Neo4jGraphRepository

        return Neo4jGraphRepository(
            url=NEO4J_URL,
            user=os.environ.get("DATAHEK_TEST_NEO4J_USER", "neo4j"),
            password=os.environ.get("DATAHEK_TEST_NEO4J_PASSWORD", ""),
        )

    def setUp(self):
        super().setUp()
        self.call(self._clear())
        self.call(self.repo.init_schema())

    async def _clear(self):
        async with self.repo._driver.session() as session:
            await (await session.run(
                "MATCH (n:DataHekNode) DETACH DELETE n")).consume()


if __name__ == "__main__":
    unittest.main()
