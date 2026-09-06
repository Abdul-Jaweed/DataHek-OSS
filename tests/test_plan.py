"""Logical plan model (ADR-003) — versioned, serializable, provider-agnostic."""
import unittest

from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode, WriteNode, validate_plan
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
