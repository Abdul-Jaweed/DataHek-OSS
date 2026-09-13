"""Human-in-the-loop — policy gating, approval service, API flow."""
import asyncio
import json
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

BIG_LIMIT_PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5000}]}"""


class _FakePlannerModel:
    def __init__(self, content):
        self._content = content

    async def complete(self, request):
        return ModelResponse(content=self._content)

    async def stream(self, request):
        yield "ok"


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)

    async def connect(self, connection):
        return object()

    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")]),
            TableMeta(name="salaries", columns=[ColumnMeta(name="amount", data_type="Int32")]),
        ])

    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}

    async def close(self, client):
        pass


def _app(model_content=BIG_LIMIT_PLAN):
    c = build_app_container()
    c.override(ModelProvider, _FakePlannerModel(model_content))
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default"),
    ]))
    return create_app(c)


class TestPolicyApprovalRules(unittest.TestCase):
    def _decision(self, table, limit):
        from datahek.defaults.policy import LocalPolicyEngine
        from datahek.engine.plan import LogicalPlan, ReadNode

        policy = LocalPolicyEngine()
        plan = LogicalPlan(nodes=[ReadNode(source=table, columns=["x"], limit=limit)])
        return asyncio.run(policy.evaluate({"plan": plan, "table": table}))

    def test_large_limit_requires_approval(self):
        d = self._decision("traces", 5000)
        self.assertEqual(d["action"], "REQUIRE_APPROVAL")

    def test_sensitive_table_requires_approval(self):
        d = self._decision("salaries", 10)
        self.assertEqual(d["action"], "REQUIRE_APPROVAL")

    def test_normal_query_allowed(self):
        d = self._decision("traces", 10)
        self.assertEqual(d["action"], "ALLOW")

    def test_unbounded_raw_scan_requires_approval(self):
        d = self._decision("traces", None)
        self.assertEqual(d["action"], "REQUIRE_APPROVAL")

    def test_unbounded_aggregate_allowed(self):
        from datahek.defaults.policy import LocalPolicyEngine
        from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode

        policy = LocalPolicyEngine()
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"],
                                           aggregates=[Aggregate(function="count", column="*", alias="n")])])
        d = asyncio.run(policy.evaluate({"plan": plan, "table": "traces"}))
        self.assertEqual(d["action"], "ALLOW")


class TestLocalApprovalService(unittest.TestCase):
    def test_lifecycle(self):
        from datahek.contracts.misc import ApprovalRequest
        from datahek.defaults.approvals import LocalApprovalService

        async def run():
            svc = LocalApprovalService()
            aid = await svc.request_approval(RequestContext(source="api"), ApprovalRequest(
                id="a1", org_id="default", project_id="default", resource_ref="c1",
                requester="datahek", reason="big export"))
            self.assertEqual(await svc.status(aid), "pending")
            await svc.decide(aid, "approved", "admin")
            self.assertEqual(await svc.status(aid), "approved")
            await svc.consume(aid)
            self.assertEqual(await svc.status(aid), "consumed")
            self.assertEqual(len(svc.list_all()), 1)

        asyncio.run(run())

    def test_unknown_id_not_found(self):
        from datahek.defaults.approvals import LocalApprovalService

        async def run():
            svc = LocalApprovalService()
            with self.assertRaises(DatahekError) as cm:
                await svc.status("nope")
            self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)

        asyncio.run(run())


class TestApprovalApiFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app())

    def test_large_limit_returns_202_with_approval_id(self):
        r = self.client.post("/ask", json={"question": "export everything", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 202, r.text)
        body = r.json()
        self.assertEqual(body["code"], "APPROVAL_REQUIRED")
        self.assertTrue(body["details"]["approval_id"])

    def test_approve_then_execute(self):
        r = self.client.post("/ask", json={"question": "export everything", "connection_id": "conn_1"})
        approval_id = r.json()["details"]["approval_id"]

        listed = self.client.get("/approvals").json()
        self.assertTrue(any(a["id"] == approval_id and a["status"] == "pending" for a in listed))

        d = self.client.post(f"/approvals/{approval_id}/decide",
                             json={"decision": "approve", "actor": "admin"})
        self.assertEqual(d.status_code, 200, d.text)
        self.assertEqual(d.json()["status"], "approved")

        r2 = self.client.post("/ask", json={
            "question": "export everything", "connection_id": "conn_1", "approval_id": approval_id})
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["rows"], [{"service": "payment-api"}])

    def test_reject_blocks_execution(self):
        r = self.client.post("/ask", json={"question": "export everything", "connection_id": "conn_1"})
        approval_id = r.json()["details"]["approval_id"]
        self.client.post(f"/approvals/{approval_id}/decide", json={"decision": "reject", "actor": "admin"})

        r2 = self.client.post("/ask", json={
            "question": "export everything", "connection_id": "conn_1", "approval_id": approval_id})
        self.assertEqual(r2.status_code, 422, r2.text)
        self.assertEqual(r2.json()["code"], "QUERY_DENIED")

    def test_normal_query_unaffected(self):
        client = TestClient(_app(json.dumps({"nodes": [
            {"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 10}]})))
        r = client.post("/ask", json={"question": "small query", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
