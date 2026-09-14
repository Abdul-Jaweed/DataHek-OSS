"""JOINs — AST model, validation, compilation, and policy coverage."""
import json
import unittest

from datahek.engine.compile import compile_sql
from datahek.engine.plan import Aggregate, Join, LogicalPlan, ReadNode, validate_plan
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.kernel.context import RequestContext

TABLES = {"traces", "service_meta"}
COLUMNS = {
    "traces": {"service", "status", "duration_ms"},
    "service_meta": {"service", "tier"},
}


def _joined_plan(**overrides):
    base = dict(
        source="traces",
        columns=["service"],
        group_by=["service"],
        aggregates=[Aggregate(function="avg", column="duration_ms", alias="avg_ms")],
        joins=[Join(table="service_meta", on_left="service", on_right="service")],
        limit=10,
    )
    base.update(overrides)
    return LogicalPlan(nodes=[ReadNode(**base)])


class TestJoinCompile(unittest.TestCase):
    def test_inner_join_sql(self):
        sql = compile_sql(_joined_plan())
        self.assertEqual(
            sql,
            "SELECT traces.service, avg(traces.duration_ms) AS avg_ms FROM traces "
            "INNER JOIN service_meta ON traces.service = service_meta.service "
            "GROUP BY traces.service LIMIT 10",
        )

    def test_left_join_sql(self):
        sql = compile_sql(_joined_plan(joins=[Join(table="service_meta", on_left="service",
                                                   on_right="service", join_type="left")]))
        self.assertIn("LEFT JOIN service_meta ON traces.service = service_meta.service", sql)

    def test_dotted_columns_kept_verbatim(self):
        sql = compile_sql(_joined_plan(columns=["service", "service_meta.tier"],
                                       group_by=["service", "service_meta.tier"],
                                       aggregates=[]))
        self.assertIn("traces.service, service_meta.tier", sql)
        self.assertIn("GROUP BY traces.service, service_meta.tier", sql)

    def test_single_table_sql_unchanged(self):
        sql = compile_sql(LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=5)]))
        self.assertEqual(sql, "SELECT service FROM traces LIMIT 5")

    def test_join_on_right_defaults_to_same_column_name(self):
        sql = compile_sql(_joined_plan(joins=[Join(table="service_meta", on_left="service")]))
        self.assertIn("ON traces.service = service_meta.service", sql)


class TestJoinValidation(unittest.TestCase):
    def test_valid_join_passes(self):
        validate_plan(_joined_plan(), tables=TABLES, columns=COLUMNS, dialect="clickhouse")

    def test_unknown_join_table_rejected(self):
        with self.assertRaises(DatahekError) as cm:
            validate_plan(_joined_plan(joins=[Join(table="nope", on_left="service")]),
                          tables=TABLES, columns=COLUMNS)
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)

    def test_unknown_join_column_rejected(self):
        with self.assertRaises(DatahekError):
            validate_plan(_joined_plan(joins=[Join(table="service_meta", on_left="missing")]),
                          tables=TABLES, columns=COLUMNS)

    def test_dotted_column_unknown_table_rejected(self):
        with self.assertRaises(DatahekError):
            validate_plan(_joined_plan(columns=["other.col"]), tables=TABLES, columns=COLUMNS)

    def test_dotted_column_unknown_column_rejected(self):
        with self.assertRaises(DatahekError):
            validate_plan(_joined_plan(columns=["service_meta.missing"]), tables=TABLES, columns=COLUMNS)

    def test_roundtrip_with_joins(self):
        plan = _joined_plan()
        restored = LogicalPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.nodes[0].joins, plan.nodes[0].joins)


class TestJoinRefNormalization(unittest.TestCase):
    def test_plain_group_by_resolves_to_joined_table(self):
        from datahek.engine.planner import _normalize_join_refs

        plan = _joined_plan(columns=["service", "service_meta.tier"],
                            group_by=["service", "tier"], aggregates=[])
        normalized = _normalize_join_refs(plan, COLUMNS)
        self.assertEqual(normalized.nodes[0].group_by, ["service", "service_meta.tier"])

    def test_ambiguous_plain_ref_left_alone(self):
        from datahek.engine.planner import _normalize_join_refs

        plan = _joined_plan(columns=["service"], group_by=["service"], aggregates=[])
        normalized = _normalize_join_refs(plan, COLUMNS)
        self.assertEqual(normalized.nodes[0].group_by, ["service"])

    def test_bare_group_by_passes_validation(self):
        plan = _joined_plan(columns=["service", "service_meta.tier"],
                            group_by=["service", "service_meta.tier"], aggregates=[])
        validate_plan(plan, tables=TABLES, columns=COLUMNS)


class TestJoinPolicy(unittest.TestCase):
    def test_sensitive_join_table_requires_approval(self):
        import asyncio
        from datahek.defaults.policy import LocalPolicyEngine

        policy = LocalPolicyEngine()
        plan = _joined_plan(source="traces", joins=[Join(table="salaries", on_left="service")])
        d = asyncio.run(policy.evaluate({"plan": plan, "tables": ["traces", "salaries"]}))
        self.assertEqual(d["action"], "REQUIRE_APPROVAL")

    def test_allowlist_covers_join_tables(self):
        import asyncio
        from datahek.defaults.policy import LocalPolicyEngine

        policy = LocalPolicyEngine(allowed_tables=["traces"])
        plan = _joined_plan()
        d = asyncio.run(policy.evaluate({"plan": plan, "tables": ["traces", "service_meta"]}))
        self.assertEqual(d["action"], "DENY")


class TestJoinApiE2E(unittest.TestCase):
    def test_joined_plan_executes_through_pipeline(self):
        from fastapi.testclient import TestClient
        from datahek.api.app import create_app
        from datahek.contracts.connections import Connection, ConnectionManager
        from datahek.contracts.models import ModelProvider, ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.defaults.connections import LocalConnectionManager
        from datahek.defaults.container import build_app_container
        from datahek.engine.executor import ProviderRegistry
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

        join_plan = json.dumps({"nodes": [{
            "type": "ReadNode", "source": "traces", "columns": ["service", "service_meta.tier"],
            "group_by": ["service", "service_meta.tier"], "limit": 5,
            "joins": [{"table": "service_meta", "join_type": "inner",
                       "on_left": "service", "on_right": "service"}]}]})

        class _Model:
            async def complete(self, request):
                system = request["messages"][0]["content"]
                if "You are an analyst" in system:
                    return ModelResponse(content="joined answer")
                if "verifier" in system.lower():
                    return ModelResponse(content=json.dumps({"ok": True, "note": "ok"}))
                return ModelResponse(content=join_plan)

            async def stream(self, request):
                yield "ok"

        class _Provider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            last_sql = None

            async def connect(self, connection):
                return object()

            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String"), ColumnMeta(name="duration_ms", data_type="Int32")]),
                    TableMeta(name="service_meta", columns=[ColumnMeta(name="service", data_type="String"), ColumnMeta(name="tier", data_type="String")]),
                ])

            async def compile_and_execute(self, client, plan, ctx):
                from datahek.engine.compile import compile_sql

                _Provider.last_sql = compile_sql(plan)
                return {"columns": [{"name": "service"}, {"name": "tier"}],
                        "rows": [("auth-service", "gold")]}

            async def close(self, client):
                pass

        c = build_app_container()
        c.override(ModelProvider, _Model())
        registry = ProviderRegistry()
        registry.register(_Provider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
        client = TestClient(create_app(c))
        r = client.post("/ask", json={"question": "show tiers per service", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("INNER JOIN service_meta", _Provider.last_sql)
        self.assertEqual(r.json()["rows"], [{"service": "auth-service", "tier": "gold"}])


if __name__ == "__main__":
    unittest.main()
