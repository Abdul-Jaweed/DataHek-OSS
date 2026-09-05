"""Schema catalog model, discovery service, and engine validation wiring."""
import asyncio
import unittest
from unittest import mock

from datahek.contracts.connections import Connection
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.plan import LogicalPlan, ReadNode, validate_plan
from datahek.engine.schema import ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext


class TestSchemaModels(unittest.TestCase):
    def test_catalog_construction(self):
        cat = SchemaCatalog(
            source="conn_1:default",
            tables=[
                TableMeta(
                    name="traces",
                    columns=[ColumnMeta(name="service", data_type="String", nullable=False)],
                    row_count=100,
                ),
            ],
        )
        self.assertEqual(cat.tables[0].name, "traces")
        self.assertEqual(cat.tables[0].columns[0].data_type, "String")

    def test_catalog_roundtrip(self):
        cat = SchemaCatalog(
            source="c:db",
            tables=[TableMeta(name="t", columns=[ColumnMeta(name="a", data_type="Int32", nullable=True)])],
        )
        restored = SchemaCatalog.from_dict(cat.to_dict())
        self.assertEqual(restored.tables[0].name, "t")
        self.assertEqual(restored.tables[0].columns[0].name, "a")

    def test_validate_shapes(self):
        cat = SchemaCatalog(
            source="c:db",
            tables=[TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])],
        )
        service = SchemaService()
        self.assertEqual(service.tables(cat), {"traces"})
        self.assertEqual(service.columns(cat), {"traces": {"service"}})


class TestSchemaService(unittest.TestCase):
    def _conn(self, provider="clickhouse"):
        return Connection(id="c1", name="ch", provider=provider, org_id="default", project_id="default")

    def _provider(self):
        p = mock.Mock()
        p.provider_id = "clickhouse"
        p.introspect = mock.AsyncMock(return_value=SchemaCatalog(
            source="c1:default",
            tables=[TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")], row_count=12)],
        ))
        return p

    def test_introspects_on_demand(self):
        service = SchemaService()
        provider = self._provider()
        ctx = RequestContext(source="api")
        cat = asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        self.assertEqual(cat.tables[0].row_count, 12)
        provider.introspect.assert_awaited_once()

    def test_cached_within_ttl(self):
        service = SchemaService(ttl_seconds=300)
        provider = self._provider()
        ctx = RequestContext(source="api")
        asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        provider.introspect.assert_awaited_once()

    def test_refreshes_after_ttl(self):
        service = SchemaService(ttl_seconds=0)
        provider = self._provider()
        ctx = RequestContext(source="api")
        asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        self.assertEqual(provider.introspect.await_count, 2)

    def test_force_refresh(self):
        service = SchemaService(ttl_seconds=300)
        provider = self._provider()
        ctx = RequestContext(source="api")
        asyncio.run(service.get_catalog(ctx, self._conn(), provider))
        asyncio.run(service.get_catalog(ctx, self._conn(), provider, force_refresh=True))
        self.assertEqual(provider.introspect.await_count, 2)


class TestEngineSchemaValidation(unittest.TestCase):
    def test_unknown_table_denied_before_execution(self):
        from datahek.engine.schema import SchemaService

        provider = mock.Mock()
        provider.provider_id = "fake"
        provider.capabilities = mock.Mock(max_result_rows=1000)
        provider.introspect = mock.AsyncMock(return_value=SchemaCatalog(
            source="c1:default",
            tables=[TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])],
        ))
        provider.compile_and_execute = mock.AsyncMock()

        registry = ProviderRegistry()
        registry.register(provider)
        service = SchemaService()
        engine = Engine(registry, schema_service=service)
        conn = Connection(id="c1", name="ch", provider="fake", org_id="default", project_id="default")

        plan = LogicalPlan(nodes=[ReadNode(source="ghost", columns=["service"])])
        with self.assertRaises(Exception) as cm:
            asyncio.run(engine.execute(RequestContext(source="api"), plan, conn))
        self.assertEqual(getattr(cm.exception, "code").value, "PLAN_INVALID")
        provider.compile_and_execute.assert_not_awaited()

    def test_valid_plan_executes(self):
        from datahek.engine.schema import SchemaService

        provider = mock.Mock()
        provider.provider_id = "fake"
        provider.capabilities = mock.Mock(max_result_rows=1000)
        provider.introspect = mock.AsyncMock(return_value=SchemaCatalog(
            source="c1:default",
            tables=[TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])],
        ))
        provider.connect = mock.AsyncMock(return_value=object())
        provider.compile_and_execute = mock.AsyncMock(
            return_value={"columns": [{"name": "service", "type": "String"}], "rows": [("api",)]})
        provider.close = mock.AsyncMock()

        registry = ProviderRegistry()
        registry.register(provider)
        engine = Engine(registry, schema_service=SchemaService())
        conn = Connection(id="c1", name="ch", provider="fake", org_id="default", project_id="default")

        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=10)])
        result = asyncio.run(engine.execute(RequestContext(source="api"), plan, conn))
        self.assertEqual(result.rows, [("api",)])
        provider.compile_and_execute.assert_awaited_once()


class TestValidatePlanWithCatalog(unittest.TestCase):
    def test_validate_uses_catalog_shapes(self):
        cat = SchemaCatalog(
            source="c:db",
            tables=[TableMeta(name="traces", columns=[ColumnMeta(name="a", data_type="Int32")])],
        )
        service = SchemaService()
        validate_plan(
            LogicalPlan(nodes=[ReadNode(source="traces", columns=["a"])]),
            service.tables(cat),
            service.columns(cat),
        )


if __name__ == "__main__":
    unittest.main()