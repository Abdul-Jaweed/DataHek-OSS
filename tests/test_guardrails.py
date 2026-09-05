"""Guardrail pipeline — typed decisions, deterministic order."""
import asyncio
import unittest

from datahek.engine.guardrails import GuardrailPipeline, PlanComplexityGuardrail, PlanReadOnlyGuardrail
from datahek.engine.plan import LogicalPlan, ReadNode, WriteNode
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.kernel.context import RequestContext


def _ctx():
    return RequestContext(source="api")


class TestGuardrailPipeline(unittest.TestCase):
    def test_all_allow_when_clean(self):
        pipe = GuardrailPipeline([PlanReadOnlyGuardrail(), PlanComplexityGuardrail()])
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=50)])
        payload = {"plan": plan, "capabilities": ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)}
        result = asyncio.run(pipe.run(_ctx(), payload))
        self.assertEqual(result.decision, "ALLOW")

    def test_plan_read_only_denies_write(self):
        pipe = GuardrailPipeline([PlanReadOnlyGuardrail()])
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        result = asyncio.run(pipe.run(_ctx(), {"plan": plan, "capabilities": None}))
        self.assertEqual(result.decision, "DENY")
        self.assertIn("read-only", result.reason)

    def test_complexity_caps_excessive_limit(self):
        pipe = GuardrailPipeline([PlanComplexityGuardrail()])
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=100_000)])
        payload = {"plan": plan, "capabilities": ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)}
        result = asyncio.run(pipe.run(_ctx(), payload))
        self.assertEqual(result.decision, "ALLOW")
        self.assertEqual(payload["plan"].nodes[0].limit, 1000)

    def test_first_decision_wins(self):
        class DenyGuardrail:
            name = "deny_first"
            stage = "plan"
            enabled = True
            async def run(self, ctx, payload):
                from datahek.contracts.guardrails import GuardrailResult
                return GuardrailResult(decision="DENY", reason="no")

        pipe = GuardrailPipeline([DenyGuardrail(), PlanReadOnlyGuardrail()])
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        result = asyncio.run(pipe.run(_ctx(), {"plan": plan, "capabilities": None}))
        self.assertEqual(result.decision, "DENY")
        self.assertEqual(result.reason, "no")

    def test_order_deterministic(self):
        pipe = GuardrailPipeline([PlanReadOnlyGuardrail(), PlanComplexityGuardrail()])
        self.assertEqual([g.name for g in pipe.guardrails], ["plan_read_only", "plan_complexity"])


if __name__ == "__main__":
    unittest.main()