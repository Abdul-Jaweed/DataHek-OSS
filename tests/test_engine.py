"""Engine executor — routes plans through capabilities, guardrails, providers."""
import asyncio
import unittest
from unittest import mock

from datahek.contracts.audit import AuditEvent
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.plan import LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode


class _RecorderSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class _FakeProvider(DataProvider):
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake", max_result_rows=10)

    def __init__(self):
        self.executed = []

    async def connect(self, connection):
        return object()

    async def ping(self, client):
        return {"ok": True}

    async def compile_and_execute(self, client, plan, ctx):
        self.executed.append(plan)
        return {"columns": [{"name": "a", "type": "Int32"}], "rows": [(1,), (2,), (3,)]}

    async def close(self, client):
        pass


class TestProviderRegistry(unittest.TestCase):
    def test_register_and_get(self):
        r = ProviderRegistry()
        r.register(_FakeProvider())
        self.assertIsInstance(r.get("fake"), _FakeProvider)

    def test_unknown_provider(self):
        r = ProviderRegistry()
        with self.assertRaises(KeyError):
            r.get("nope")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.provider = _FakeProvider()
        registry = ProviderRegistry()
        registry.register(self.provider)
        self.engine = Engine(registry)
        self.ctx = RequestContext(source="api")
        self.conn = Connection(id="c1", name="c", provider="fake", org_id="default", project_id="default")

    def test_execute_read_plan(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=5)])
        result = asyncio.run(self.engine.execute(self.ctx, plan, self.conn))
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.columns[0]["name"], "a")
        self.assertFalse(result.truncated)

    def test_execute_truncates_to_capability_limit(self):
        provider = _FakeProvider()
        provider.capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=2)
        registry = ProviderRegistry()
        registry.register(provider)
        engine = Engine(registry)
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=100)])
        result = asyncio.run(engine.execute(self.ctx, plan, self.conn))
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(plan.nodes[0].limit, 2)

    def test_write_plan_denied(self):
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(self.engine.execute(self.ctx, plan, self.conn))
        self.assertEqual(cm.exception.code, ErrorCode.QUERY_DENIED)

    def test_connection_provider_mismatch(self):
        conn = Connection(id="c2", name="c", provider="clickhouse", org_id="default", project_id="default")
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(self.engine.execute(self.ctx, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]), conn))
        self.assertEqual(cm.exception.code, ErrorCode.VALIDATION)

    def test_provider_error_never_leaks_driver_text(self):
        class Broken(_FakeProvider):
            async def compile_and_execute(self, client, plan, ctx):
                raise RuntimeError("driver internal /tmp/x secret")

        registry = ProviderRegistry()
        registry.register(Broken())
        engine = Engine(registry)
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(engine.execute(self.ctx, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]), self.conn))
        self.assertNotIn("secret", str(cm.exception))
        self.assertEqual(cm.exception.code, ErrorCode.CONNECTION_FAILED)

    def test_connect_error_classified_not_raw(self):
        class Unresolvable(_FakeProvider):
            async def connect(self, connection):
                raise RuntimeError("failed to resolve host 'db.internal' secret-token")

        registry = ProviderRegistry()
        registry.register(Unresolvable())
        engine = Engine(registry)
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(engine.execute(self.ctx, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]), self.conn))
        self.assertEqual(cm.exception.code, ErrorCode.CONNECTION_FAILED)
        self.assertNotIn("secret-token", str(cm.exception))
        self.assertNotIn("db.internal", str(cm.exception))


class TestEngineAudit(unittest.TestCase):
    def setUp(self):
        self.sink = _RecorderSink()
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        self.engine = Engine(registry, audit_sink=self.sink)
        self.ctx = RequestContext(source="api", user_id="alice")
        self.conn = Connection(id="c1", name="c", provider="fake", org_id="default", project_id="default")

    def test_successful_execution_audited(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=5)])
        asyncio.run(self.engine.execute(self.ctx, plan, self.conn))
        types = [e.event_type for e in self.sink.events]
        self.assertIn("guardrail.decision", types)
        self.assertIn("query.execution", types)
        exec_evt = self.sink.events[-1]
        self.assertEqual(exec_evt.actor, "alice")
        self.assertEqual(exec_evt.resource_ref, "c1")
        self.assertEqual(exec_evt.payload["outcome"], "completed")
        self.assertIn("row_count", exec_evt.payload)
        self.assertEqual(exec_evt.tenant, {"org": "default", "project": "default"})

    def test_denied_plan_audited_as_deny(self):
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        with self.assertRaises(DatahekError):
            asyncio.run(self.engine.execute(self.ctx, plan, self.conn))
        decision_evts = [e for e in self.sink.events if e.event_type == "guardrail.decision"]
        self.assertEqual(len(decision_evts), 1)
        self.assertEqual(decision_evts[0].decision, "DENY")
        self.assertNotIn("query.execution", [e.event_type for e in self.sink.events])

    def test_failed_execution_audited_with_sanitized_code(self):
        class Broken(_FakeProvider):
            async def compile_and_execute(self, client, plan, ctx):
                raise RuntimeError("driver internal /tmp/x secret")

        registry = ProviderRegistry()
        registry.register(Broken())
        engine = Engine(registry, audit_sink=self.sink)
        with self.assertRaises(DatahekError):
            asyncio.run(engine.execute(self.ctx, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]), self.conn))
        exec_evt = [e for e in self.sink.events if e.event_type == "query.execution"][-1]
        self.assertEqual(exec_evt.payload["outcome"], "failed")
        self.assertEqual(exec_evt.payload["error_code"], "CONNECTION_FAILED")
        self.assertNotIn("secret", str(exec_evt.payload))


if __name__ == "__main__":
    unittest.main()