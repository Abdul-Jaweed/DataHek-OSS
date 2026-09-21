"""Logical plan model (ADR-006) — versioned, serializable, provider-agnostic."""
import unittest

from datahek.engine.plan import Aggregate, Join, LogicalPlan, ReadNode, WriteNode, validate_plan
from datahek.kernel.errors import DatahekError, ErrorCode


class TestPlanModel(unittest.TestCase):
    def test_read_plan_construction(self):
        plan = LogicalPlan(nodes=[
            ReadNode(source="traces", columns=["service", "duration_ms"], limit=100),
        ])
        self.assertTrue(plan.read_only)
        self.assertEqual(plan.version, 1)

    def test_write_plan_not_read_only(self):
        plan = LogicalPlan(nodes=[WriteNode(source="traces", operation="delete")])
        self.assertFalse(plan.read_only)

    def test_aggregates(self):
        plan = LogicalPlan(nodes=[
            ReadNode(
                source="traces",
                columns=["service"],
                group_by=["service"],
                aggregates=[Aggregate(function="count", column="*", alias="n")],
                order_by=["n DESC"],
                limit=10,
            ),
        ])
        node = plan.nodes[0]
        self.assertEqual(node.aggregates[0].alias, "n")
        self.assertEqual(node.limit, 10)

    def test_serialization_roundtrip(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=5)])
        restored = LogicalPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.nodes[0].source, "t")
        self.assertEqual(restored.nodes[0].limit, 5)

    def test_plan_validation_unknown_source(self):
        plan = LogicalPlan(nodes=[ReadNode(source="ghost", columns=["a"])])
        with self.assertRaises(DatahekError) as cm:
            validate_plan(plan, tables={"traces"}, columns={"traces": {"a", "b"}})
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)

    def test_plan_validation_unknown_column(self):
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["nope"])])
        with self.assertRaises(DatahekError):
            validate_plan(plan, tables={"traces"}, columns={"traces": {"a"}})

    def test_plan_validation_group_by_must_be_in_columns(self):
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["a"], group_by=["b"])])
        with self.assertRaises(DatahekError):
            validate_plan(plan, tables={"traces"}, columns={"traces": {"a"}})

    def test_plan_validation_ok(self):
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["a"], limit=10)])
        validate_plan(plan, tables={"traces"}, columns={"traces": {"a"}})

    def test_from_dict_normalizes_object_order_by(self):
        plan = LogicalPlan.from_dict({"nodes": [
            {"type": "ReadNode", "source": "traces", "columns": ["a"],
             "order_by": [{"column": "a", "direction": "DESC"}], "limit": 5},
        ]})
        self.assertEqual(plan.nodes[0].order_by, ["a DESC"])

    def test_from_dict_keeps_string_order_by(self):
        plan = LogicalPlan.from_dict({"nodes": [
            {"type": "ReadNode", "source": "traces", "columns": ["a"],
             "order_by": ["a ASC"], "limit": 5},
        ]})
        self.assertEqual(plan.nodes[0].order_by, ["a ASC"])


if __name__ == "__main__":
    unittest.main()

class TestAggregatePlanValidation(unittest.TestCase):
    def test_grouped_columns_with_aggregates_ok(self):
        from datahek.engine.plan import Aggregate

        plan = LogicalPlan(nodes=[ReadNode(
            source="traces", columns=["service"],
            group_by=["service"],
            aggregates=[Aggregate(function="count", column="*", alias="n")],
        )])
        validate_plan(plan, tables={"traces"}, columns={"traces": {"service"}})


class TestStarColumnWithAggregates(unittest.TestCase):
    def test_star_column_allowed_with_aggregates(self):
        from datahek.engine.plan import Aggregate

        plan = LogicalPlan(nodes=[ReadNode(
            source="traces", columns=["*"],
            aggregates=[Aggregate(function="count", column="*", alias="n")],
        )])
        validate_plan(plan, tables={"traces"}, columns={"traces": {"service", "status", "duration_ms"}})


class TestAggregateColumnValidation(unittest.TestCase):
    def test_aggregate_on_unknown_column_rejected(self):
        from datahek.engine.plan import Aggregate

        plan = LogicalPlan(nodes=[ReadNode(
            source="traces", columns=["service"],
            group_by=["service"],
            aggregates=[Aggregate(function="avg", column="duration", alias="avg_duration")],
        )])
        with self.assertRaises(DatahekError) as cm:
            validate_plan(plan, tables={"traces"}, columns={"traces": {"service", "status"}})
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)
        self.assertIn("duration", str(cm.exception))

    def test_aggregate_on_known_column_accepted(self):
        from datahek.engine.plan import Aggregate

        plan = LogicalPlan(nodes=[ReadNode(
            source="traces", columns=["service"],
            group_by=["service"],
            aggregates=[Aggregate(function="avg", column="duration_ms", alias="avg_duration")],
        )])
        validate_plan(plan, tables={"traces"}, columns={"traces": {"service", "duration_ms"}})


class TestDialectFunctionValidation(unittest.TestCase):
    def _plan(self, function, column="duration_ms"):
        from datahek.engine.plan import Aggregate
        return LogicalPlan(nodes=[ReadNode(
            source="traces", columns=["service"],
            group_by=["service"],
            aggregates=[Aggregate(function=function, column=column, alias="agg")],
        )])

    def test_clickhouse_uniq_allowed(self):
        from datahek.engine.plan import Aggregate
        validate_plan(self._plan("uniq"), tables={"traces"},
                      columns={"traces": {"service", "duration_ms"}}, dialect="clickhouse")

    def test_postgres_uniq_rejected(self):
        from datahek.engine.plan import Aggregate
        with self.assertRaises(DatahekError) as cm:
            validate_plan(self._plan("uniq"), tables={"traces"},
                          columns={"traces": {"service", "duration_ms"}}, dialect="postgres")
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)

    def test_postgres_count_distinct_allowed(self):
        validate_plan(self._plan("count_distinct", "service"), tables={"traces"},
                      columns={"traces": {"service", "duration_ms"}}, dialect="postgres")

    def test_count_distinct_star_rejected(self):
        from datahek.engine.plan import Aggregate
        with self.assertRaises(DatahekError):
            validate_plan(self._plan("count_distinct", "*"), tables={"traces"},
                          columns={"traces": {"service", "duration_ms"}}, dialect="postgres")

    def test_unknown_function_rejected(self):
        with self.assertRaises(DatahekError):
            validate_plan(self._plan("median"), tables={"traces"},
                          columns={"traces": {"service", "duration_ms"}}, dialect="postgres")


class TestDateTruncExpressions(unittest.TestCase):
    TABLES = {"events"}
    COLUMNS = {"events": {"event_time", "service"}}

    def _plan(self, columns, group_by):
        return LogicalPlan(nodes=[ReadNode(source="events", columns=columns,
                                           group_by=group_by)])

    def test_accepted_on_postgres(self):
        expression = "DATE_TRUNC('month', event_time)"
        validate_plan(self._plan([expression], [expression]),
                      tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_rejected_on_unsupported_dialect(self):
        expression = "date_trunc('month', event_time)"
        with self.assertRaises(DatahekError) as caught:
            validate_plan(self._plan([expression], [expression]),
                          tables=self.TABLES, columns=self.COLUMNS, dialect="sqlite")
        self.assertEqual(caught.exception.code, ErrorCode.PLAN_INVALID)
        self.assertIn("DATE_TRUNC", str(caught.exception))

    def test_unknown_inner_column_rejected(self):
        expression = "date_trunc('month', nope)"
        with self.assertRaises(DatahekError):
            validate_plan(self._plan([expression], [expression]),
                          tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_invalid_unit_rejected(self):
        expression = "date_trunc('fortnight', event_time)"
        with self.assertRaises(DatahekError):
            validate_plan(self._plan([expression], [expression]),
                          tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_compiler_keeps_expression_unqualified(self):
        from datahek.engine.compile import compile_sql

        expression = "date_trunc('month', event_time)"
        sql = compile_sql(self._plan([expression], [expression]))
        self.assertIn(expression, sql)
        self.assertNotIn("events.date_trunc", sql)

    def test_alias_on_expression_and_group_by_matches_by_parts(self):
        validate_plan(
            self._plan(["date_trunc('day', event_time) AS event_date"], ["DATE_TRUNC('day', event_time)"]),
            tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_compiler_keeps_aliased_expression_in_select(self):
        from datahek.engine.compile import compile_sql

        plan = self._plan(["date_trunc('month', event_time) AS month"],
                          ["date_trunc('month', event_time)"])
        sql = compile_sql(plan)
        self.assertIn("date_trunc('month', event_time) AS month", sql)
        self.assertIn("GROUP BY date_trunc('month', event_time)", sql)

    def test_star_select_allowed_without_aggregates(self):
        validate_plan(self._plan(["*"], []), tables=self.TABLES, columns=self.COLUMNS,
                      dialect="postgres")

    def test_aggregate_alias_in_select_is_ignored(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["service", "distinct_operations"],
            group_by=["service"],
            aggregates=[Aggregate(function="count_distinct", column="operation",
                                  alias="distinct_operations")])])
        validate_plan(plan, tables=self.TABLES,
                      columns={"events": {"service", "operation"}}, dialect="postgres")

    def test_order_by_aggregate_alias_accepted(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["service"], group_by=["service"],
            aggregates=[Aggregate(function="count", column="*", alias="n")],
            order_by=["n DESC"])])
        validate_plan(plan, tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_order_by_select_alias_accepted(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["date_trunc('month', event_time) AS month"],
            group_by=["date_trunc('month', event_time)"], order_by=["month"])])
        validate_plan(plan, tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")

    def test_order_by_unknown_reference_rejected(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["service"], group_by=["service"],
            aggregates=[Aggregate(function="count", column="*", alias="n")],
            order_by=["month"])])
        with self.assertRaises(DatahekError) as caught:
            validate_plan(plan, tables=self.TABLES, columns=self.COLUMNS, dialect="postgres")
        self.assertIn("ORDER BY", str(caught.exception))


class TestSelfJoinRejected(unittest.TestCase):
    def test_self_join_is_rejected(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["service"],
            joins=[Join(table="events", on_left="span_id", on_right="parent_span_id")])])
        with self.assertRaises(DatahekError) as caught:
            validate_plan(plan, tables={"events"}, columns={"events": {"service"}},
                          dialect="postgres")
        self.assertEqual(caught.exception.code, ErrorCode.PLAN_INVALID)
        self.assertIn("Self-joins", str(caught.exception))


class TestTypeAwareValidation(unittest.TestCase):
    def _validate(self, plan, types):
        validate_plan(plan, tables=set(types), columns={t: set(c) for t, c in types.items()},
                      dialect="postgres", column_types=types)

    def test_empty_plan_rejected(self):
        with self.assertRaises(DatahekError) as cm:
            self._validate(LogicalPlan(nodes=[]), {})
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)

    def test_sum_on_boolean_rejected(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events",
            aggregates=[Aggregate(function="sum", column="is_error", alias="n")],
        )])
        with self.assertRaises(DatahekError) as cm:
            self._validate(plan, {"events": {"is_error": "boolean"}})
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)
        self.assertIn("numeric", str(cm.exception))

    def test_avg_on_text_rejected(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events",
            aggregates=[Aggregate(function="avg", column="service_name", alias="a")],
        )])
        with self.assertRaises(DatahekError):
            self._validate(plan, {"events": {"service_name": "text"}})

    def test_sum_on_numeric_allowed(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events",
            aggregates=[Aggregate(function="sum", column="duration_ms", alias="total")],
        )])
        self._validate(plan, {"events": {"duration_ms": "double precision"}})

    def test_join_incompatible_types_rejected(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["x"],
            joins=[Join(table="sales", on_left="product_id", on_right="id")],
        )])
        with self.assertRaises(DatahekError) as cm:
            self._validate(plan, {"events": {"x": "text", "product_id": "text"},
                                  "sales": {"id": "integer"}})
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)
        self.assertIn("incompatible", str(cm.exception))

    def test_join_compatible_types_allowed(self):
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["x"],
            joins=[Join(table="sales", on_left="product_id", on_right="id")],
        )])
        self._validate(plan, {"events": {"x": "text", "product_id": "text"},
                              "sales": {"id": "character varying"}})

    def test_type_family_public_helper(self):
        from datahek.engine.plan import type_family

        self.assertEqual(type_family("double precision"), "number")
        self.assertEqual(type_family("character varying"), "string")
        self.assertEqual(type_family("timestamp with time zone"), "time")
        self.assertEqual(type_family("boolean"), "bool")
        self.assertEqual(type_family("jsonb"), "string")

    def test_compile_empty_plan_raises_plan_invalid(self):
        from datahek.engine.compile import compile_sql

        with self.assertRaises(DatahekError) as cm:
            compile_sql(LogicalPlan(nodes=[]))
        self.assertEqual(cm.exception.code, ErrorCode.PLAN_INVALID)
