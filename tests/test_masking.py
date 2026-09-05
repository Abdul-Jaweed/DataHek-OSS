"""Result masking — sensitive columns masked before reasoning/return."""
import asyncio
import unittest

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.guardrails import redact_pii
from datahek.defaults.masking import TagBasedMaskingPolicy
from datahek.engine.executor import Engine, ExecutionInfo, ProviderRegistry, QueryResult
from datahek.engine.masking import mask_result
from datahek.engine.plan import LogicalPlan, ReadNode
from datahek.engine.schema import ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext


def _result():
    return QueryResult(
        columns=[{"name": "service", "type": "String"}, {"name": "email", "type": "String"}],
        rows=[("payment-api", "alice@example.com")],
        row_count=1,
        execution=ExecutionInfo(provider_id="clickhouse"),
    )


class TestMaskResult(unittest.TestCase):
    def test_masks_only_sensitive_columns(self):
        masked = mask_result(_result(), sensitive={"email"})
        self.assertEqual(masked.rows, [("payment-api", "***")])
        self.assertEqual(masked.columns, _result().columns)

    def test_unknown_sensitive_column_ignored(self):
        masked = mask_result(_result(), sensitive={"nope"})
        self.assertEqual(masked.rows, [("payment-api", "alice@example.com")])


class TestTagBasedPolicy(unittest.TestCase):
    def _catalog(self):
        return SchemaCatalog(source="c1:default", tables=[
            TableMeta(name="customers", columns=[
                ColumnMeta(name="email", data_type="String", semantic_tags=frozenset({"pii"})),
                ColumnMeta(name="revenue", data_type="Float64", semantic_tags=frozenset({"sensitive"})),
                ColumnMeta(name="name", data_type="String"),
            ]),
        ])

    def test_finds_sensitive_columns_for_plan_sources(self):
        policy = TagBasedMaskingPolicy()
        plan = LogicalPlan(nodes=[ReadNode(source="customers", columns=["email", "revenue", "name"])])
        sensitive = asyncio.run(policy.sensitive_columns(RequestContext(source="api"), plan, self._catalog()))
        self.assertEqual(sensitive, {"email", "revenue"})

    def test_other_sources_untouched(self):
        policy = TagBasedMaskingPolicy()
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["total"])])
        sensitive = asyncio.run(policy.sensitive_columns(RequestContext(source="api"), plan, self._catalog()))
        self.assertEqual(sensitive, set())


class TestEngineMasking(unittest.TestCase):
    def test_sensitive_rows_masked_before_return(self):
        class FakeProvider:
            provider_id = "fake"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="customers", columns=[
                        ColumnMeta(name="email", data_type="String", semantic_tags=frozenset({"pii"})),
                        ColumnMeta(name="name", data_type="String"),
                    ])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "email", "type": "String"}, {"name": "name", "type": "String"}],
                        "rows": [("alice@example.com", "Alice")]}
            async def close(self, client): pass

        registry = ProviderRegistry()
        registry.register(FakeProvider())
        service = SchemaService()
        engine = Engine(registry, schema_service=service, masking_policy=TagBasedMaskingPolicy())
        ctx = RequestContext(source="api")
        conn = Connection(id="c1", name="c", provider="fake", org_id="default", project_id="default")
        plan = LogicalPlan(nodes=[ReadNode(source="customers", columns=["email", "name"])])
        result = asyncio.run(engine.execute(ctx, plan, conn))
        self.assertEqual(result.rows, [("***", "Alice")])

    def test_no_policy_no_masking(self):
        class FakeProvider:
            provider_id = "fake"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "email", "type": "String"}], "rows": [("alice@example.com",)]}
            async def close(self, client): pass

        registry = ProviderRegistry()
        registry.register(FakeProvider())
        engine = Engine(registry)
        conn = Connection(id="c1", name="c", provider="fake", org_id="default", project_id="default")
        result = asyncio.run(engine.execute(
            RequestContext(source="api"), LogicalPlan(nodes=[ReadNode(source="t", columns=["email"])]), conn))
        self.assertEqual(result.rows, [("alice@example.com",)])


class TestRedactPii(unittest.TestCase):
    def test_redacts_email_and_phone(self):
        text = "Contact alice@example.com or 555-123-4567 for help."
        out = redact_pii(text)
        self.assertNotIn("alice@example.com", out)
        self.assertNotIn("555-123-4567", out)
        self.assertIn("[EMAIL]", out)
        self.assertIn("[PHONE]", out)

    def test_plain_text_untouched(self):
        text = "There are 42 rows."
        self.assertEqual(redact_pii(text), text)

    def test_api_answer_redacted(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.contracts.reasoner import Reasoner
        from datahek.engine.reasoner import ModelReasoner

        PLAN = """{"nodes": [{"type": "ReadNode", "source": "customers", "columns": ["email"], "limit": 5}]}"""

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content=PLAN)
            async def stream(self, request):
                yield PLAN

        class ReasonerModel:
            async def complete(self, request):
                return ModelResponse(content="Customer contact: alice@example.com")
            async def stream(self, request):
                yield "ok"

        class FakeProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="customers", columns=[
                        ColumnMeta(name="email", data_type="String", semantic_tags=frozenset({"pii"}))])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "email", "type": "String"}], "rows": [("alice@example.com",)]}
            async def close(self, client): pass

        container = build_app_container()
        from datahek.contracts.models import ModelProvider
        container.override(ModelProvider, FakeModel())
        container.override(Reasoner, ModelReasoner(ReasonerModel()))
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        client = TestClient(create_app(container))

        conn_id = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"}).json()["id"]
        r = client.post("/ask", json={"question": "customers?", "connection_id": conn_id})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotIn("alice@example.com", body["answer"])
        self.assertEqual(body["rows"], [{"email": "***"}])


if __name__ == "__main__":
    unittest.main()