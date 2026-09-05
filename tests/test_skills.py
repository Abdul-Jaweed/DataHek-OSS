"""Skill registry — domain guidance injected into the planner prompt."""
import asyncio
import unittest

from datahek.engine.skills import Skill, SkillRegistry, build_skill_prompt, builtin_skills


class TestSkillRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.registry.register(Skill(
            name="analytics", priority=5,
            triggers=["count", "top", "distribution", "breakdown", "sum", "average"],
            guidance="Use group-by aggregations and top-N patterns.",
        ))
        self.registry.register(Skill(
            name="timeseries", priority=10,
            triggers=["trend", "hourly", "daily", "over time", "last week", "trending"],
            guidance="Group by time buckets and use ordering for trends.",
        ))
        self.registry.register(Skill(
            name="debugging", priority=10,
            triggers=["error", "root cause", "why", "failed", "anomaly"],
            guidance="Filter for failures and correlate causes.",
        ))

    def test_register_and_list(self):
        names = [s.name for s in self.registry.all()]
        self.assertEqual(set(names), {"analytics", "timeseries", "debugging"})

    def test_multiple_skills_match(self):
        matched = self.registry.match("why did the error trend change over the last week?")
        names = {s.name for s in matched}
        self.assertEqual(names, {"debugging", "timeseries"})

    def test_priority_ordering(self):
        matched = self.registry.match("show top counts of errors by hour")
        priorities = [s.priority for s in matched]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_no_match_returns_empty(self):
        self.assertEqual(self.registry.match("hello there"), [])

    def test_build_prompt_includes_guidance(self):
        matched = self.registry.match("top counts of errors by hour")
        prompt = build_skill_prompt(matched)
        self.assertIn("Use group-by aggregations", prompt)
        self.assertIn("Filter for failures", prompt)


class TestBuiltinSkills(unittest.TestCase):
    def test_four_default_skills(self):
        skills = builtin_skills()
        self.assertEqual(len(skills), 4)
        names = {s.name for s in skills}
        self.assertEqual(names, {"analytics", "timeseries", "debugging", "data_exploration"})


class TestPlannerSkillsIntegration(unittest.TestCase):
    def test_planner_prompt_contains_skill_guidance(self):
        import json
        import time

        from datahek.contracts.connections import Connection
        from datahek.contracts.models import ModelResponse
        from datahek.engine.planner import Planner
        from datahek.engine.schema import _CatalogEntry, ColumnMeta, SchemaCatalog, SchemaService, TableMeta

        class CapturingModel:
            def __init__(self):
                self.requests = []

            async def complete(self, request):
                self.requests.append(request)
                return ModelResponse(content='{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}')
            async def stream(self, request):
                yield ""

        catalog = SchemaCatalog(source="c1:default", tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
        service = SchemaService()
        service._entries["c1:default"] = _CatalogEntry(catalog=catalog, fetched_at=time.time())
        model = CapturingModel()
        registry = SkillRegistry()
        registry.register(Skill(name="analytics", priority=5, triggers=["count"],
                                guidance="Use group-by aggregations."))
        planner = Planner(model=model, schema_service=service, skills=registry)
        conn = Connection(id="c1", name="ch", provider="clickhouse", org_id="default", project_id="default")
        provider = type("P", (), {"provider_id": "clickhouse"})()

        asyncio.run(planner.plan("count how many traces?", __import__("datahek.kernel.context", fromlist=["RequestContext"]).RequestContext(source="api"), conn, provider))
        prompt = model.requests[0]["messages"][-1]["content"]
        self.assertIn("Use group-by aggregations", prompt)

    def test_no_skills_no_guidance(self):
        import json
        import time

        from datahek.contracts.connections import Connection
        from datahek.contracts.models import ModelResponse
        from datahek.engine.planner import Planner
        from datahek.engine.schema import _CatalogEntry, ColumnMeta, SchemaCatalog, SchemaService, TableMeta

        class CapturingModel:
            def __init__(self):
                self.requests = []

            async def complete(self, request):
                self.requests.append(request)
                return ModelResponse(content='{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}')
            async def stream(self, request):
                yield ""

        catalog = SchemaCatalog(source="c1:default", tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
        service = SchemaService()
        service._entries["c1:default"] = _CatalogEntry(catalog=catalog, fetched_at=time.time())
        model = CapturingModel()
        planner = Planner(model=model, schema_service=service)
        conn = Connection(id="c1", name="ch", provider="clickhouse", org_id="default", project_id="default")
        provider = type("P", (), {"provider_id": "clickhouse"})()

        asyncio.run(planner.plan("count how many traces?", __import__("datahek.kernel.context", fromlist=["RequestContext"]).RequestContext(source="api"), conn, provider))
        prompt = model.requests[0]["messages"][-1]["content"]
        self.assertNotIn("Use group-by aggregations", prompt)


if __name__ == "__main__":
    unittest.main()