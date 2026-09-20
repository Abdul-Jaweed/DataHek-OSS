"""InMemoryGraphRepository — passes the shared contract."""
import unittest

from datahek.context.graph.memory import InMemoryGraphRepository

try:
    import graph_repository_contract as contract
except ImportError:  # pragma: no cover - module-path invocation
    from tests import graph_repository_contract as contract


class TestInMemoryGraph(contract.GraphRepositoryContract):
    def make_repo(self):
        return InMemoryGraphRepository()


if __name__ == "__main__":
    unittest.main()
