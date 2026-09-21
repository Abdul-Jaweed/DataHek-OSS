"""Row-level filters — FILTER guardrail decisions append predicates to plans."""
import asyncio
import unittest

from datahek.contracts.audit import AuditEvent, AuditSink
from datahek.contracts.connections import Connection
from datahek.contracts.guardrails import GuardrailResult
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.engine.executor import Engine, ProviderRegistry, apply_row_filters
from datahek.engine.plan import LogicalPlan, ReadNode
from datahek.kernel.context import RequestContext


def _plan(*sources, filter_value=None):
    return LogicalPlan(nodes=[
        ReadNode(source=source, columns=["id"], filter=filter_value)
        for source in sources])


class TestApplyRowFilters(unittest.TestCase):
    def test_predicate_appended_to_matching_table(self):
        plan = apply_row_filters(_plan("orders", "customers"),
                                 [{"table": "orders", "predicate": "org_id = 'acme'"}])
        self.assertEqual(plan.nodes[0].filter, "(org_id = 'acme')")
        self.assertIsNone(plan.nodes[1].filter)

    def test_existing_filter_is_anded(self):
        plan = apply_row_filters(_plan("orders", filter_value="amount > 10"),
                                 [{"table": "orders", "predicate": "org_id = 'acme'"}])
        self.assertEqual(plan.nodes[0].filter, "(amount > 10) AND (org_id = 'acme')")

    def test_multiple_filters_and_wildcard(self):
        plan = apply_row_filters(
            _plan("orders"),
            [{"table": "orders", "predicate": "org_id = 'acme'"},
             {"table": "*", "predicate": "deleted_at IS NULL"}])
        self.assertEqual(plan.nodes[0].filter,
                         "(org_id = 'acme') AND (deleted_at IS NULL)")

    def test_original_plan_is_unchanged(self):
        original = _plan("orders")
        apply_row_filters(original, [{"table": "orders", "predicate": "org_id = 'acme'"}])
        self.assertIsNone(original.nodes[0].filter)

    def test_no_filters_returns_plan(self):
        original = _plan("orders")
        self.assertIs(apply_row_filters(original, []), original)


class _FilterPolicy:
    async def evaluate(self, context):
        return {"action": "FILTER", "reason": "row-level security",
                "policy_version": "rls-1",
                "filters": [{"table": "orders", "predicate": "org_id = 'acme'"}]}


class _FakeProvider:
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake",
                                         read_only=ReadOnlyLevel.STRUCTURAL,
                                         max_result_rows=1000)

    def __init__(self):
        self.seen_filter = None

    async def connect(self, connection):
        return object()

    async def compile_and_execute(self, client, plan, ctx):
        self.seen_filter = plan.nodes[0].filter
        return {"columns": [{"name": "n", "type": "Int"}], "rows": [(1,)]}

    async def ping(self, client):
        return {"ok": True}

    async def close(self, client):
        pass


class _CapturingAudit(AuditSink):
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class TestExecutorAppliesFilters(unittest.TestCase):
    def test_filter_decision_rewrites_plan_and_audits(self):
        provider = _FakeProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        audit = _CapturingAudit()
        engine = Engine(registry, audit_sink=audit, policy=_FilterPolicy(),
                        schema_service=None)
        ctx = RequestContext(source="api", organization_id="acme", user_id="alice")
        connection = Connection(id="c1", name="fake", provider="fake",
                                org_id="acme", project_id="default")
        result = asyncio.run(engine.execute(ctx, _plan("orders"), connection))

        self.assertEqual(result.row_count, 1)
        self.assertEqual(provider.seen_filter, "(org_id = 'acme')")
        guardrail = [e for e in audit.events if e.event_type == "guardrail.decision"][0]
        self.assertEqual(guardrail.decision, "FILTER")
        self.assertEqual(guardrail.policy_version, "rls-1")
        self.assertEqual(guardrail.payload["filters"],
                         [{"table": "orders", "predicate": "org_id = 'acme'"}])

    def test_filter_does_not_apply_to_other_tables(self):
        provider = _FakeProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        engine = Engine(registry, policy=_FilterPolicy(), schema_service=None)
        ctx = RequestContext(source="api", organization_id="acme")
        connection = Connection(id="c1", name="fake", provider="fake",
                                org_id="acme", project_id="default")
        asyncio.run(engine.execute(ctx, _plan("customers"), connection))
        self.assertIsNone(provider.seen_filter)


if __name__ == "__main__":
    unittest.main()
