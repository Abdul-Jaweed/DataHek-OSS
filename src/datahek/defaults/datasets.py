"""Evaluation dataset runner — curated offline regression cases + report.

Cases execute the real engine (plan → validation → guardrails → execution)
against a scripted in-memory provider — deterministic, no network needed.
"""
import time
import logging
from dataclasses import dataclass
from typing import Literal

from datahek.contracts.connections import Connection
from datahek.contracts.evaluation import EvaluationStore
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode, WriteNode
from datahek.engine.schema import _CatalogEntry, ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    plan: LogicalPlan
    expect: Literal["ok", "denied", "invalid"] = "ok"


class _DatasetProvider(DataProvider):
    """Scripted in-memory provider for offline evaluation runs."""

    provider_id = "dataset"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL, dialect="clickhouse",
        features=frozenset({"schema_introspection", "row_counts"}),
        read_only=ReadOnlyLevel.STRUCTURAL, max_result_rows=1000,
    )

    _CATALOG = SchemaCatalog(source="c1:default", tables=[
        TableMeta(name="traces", columns=[
            ColumnMeta(name="service", data_type="String"),
            ColumnMeta(name="status", data_type="String"),
            ColumnMeta(name="duration_ms", data_type="UInt32"),
        ], row_count=100),
        TableMeta(name="orders", columns=[
            ColumnMeta(name="region", data_type="String"),
            ColumnMeta(name="total_amount", data_type="Float64"),
        ], row_count=50),
    ])

    async def connect(self, connection: Connection):
        return object()

    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> SchemaCatalog:
        return self._CATALOG

    async def compile_and_execute(self, client, plan, ctx):
        rows = [("payment-api",), ("auth-service",)] if "traces" in plan.nodes[0].source else [("west",), ("east",)]
        columns = [{"name": c, "type": "Any"} for c in plan.nodes[0].columns]
        return {"columns": columns, "rows": rows}

    async def close(self, client):
        pass


def builtin_cases() -> list[EvaluationCase]:
    return [
        EvaluationCase(
            name="analytics.top_services",
            plan=LogicalPlan(nodes=[ReadNode(
                source="traces", columns=["service"], filter="status = 'error'",
                group_by=["service"],
                aggregates=[Aggregate(function="count", column="*", alias="n")],
                order_by=["n DESC"], limit=10)]),
            expect="ok",
        ),
        EvaluationCase(
            name="safety.drop_attempt",
            plan=LogicalPlan(nodes=[WriteNode(source="traces", operation="drop")]),
            expect="denied",
        ),
        EvaluationCase(
            name="unknown_table",
            plan=LogicalPlan(nodes=[ReadNode(source="ghost_table", columns=["x"], limit=5)]),
            expect="invalid",
        ),
    ]


class DatasetRunner:
    """Run curated cases through the real engine and produce a report."""

    def __init__(self, store: EvaluationStore | None = None):
        self._store = store
        self._provider = _DatasetProvider()

    async def run(self, ctx: RequestContext, connection: Connection,
                  cases: list[EvaluationCase] | None = None) -> dict:
        cases = cases or builtin_cases()
        registry = ProviderRegistry()
        registry.register(self._provider)
        service = SchemaService()
        service._entries["c1:default"] = _CatalogEntry(
            catalog=self._provider._CATALOG, fetched_at=time.time())
        engine = Engine(registry, schema_service=service)

        results = []
        for case in cases:
            passed, scores, error = await self._run_case(engine, ctx, connection, case)
            if self._store is not None:
                await self._store.record(ctx, {
                    "id": case.name, "org_id": ctx.organization_id, "project_id": ctx.project_id,
                    "scores": scores, "status": "passed" if passed else "failed",
                })
            results.append({
                "name": case.name, "passed": passed, "scores": scores,
                "error": error,
            })
            logger.info("Evaluation case '%s': %s", case.name, "PASS" if passed else "FAIL")

        passed = sum(1 for r in results if r["passed"])
        return {
            "total": len(results),
            "passed": passed,
            "pass_rate": passed / len(results) if results else 0.0,
            "cases": results,
        }

    async def _run_case(self, engine: Engine, ctx: RequestContext, connection: Connection,
                        case: EvaluationCase) -> tuple[bool, dict, str | None]:
        scores = {"plan_validity": 1.0, "safety": 1.0, "execution": 0.0, "latency": 1.0}
        try:
            result = await engine.execute(ctx, case.plan, connection)
            ok = case.expect == "ok"
            scores["execution"] = 1.0
            return ok, scores, None
        except DatahekError as e:
            if e.code == ErrorCode.QUERY_DENIED:
                scores["safety"] = 0.0
                ok = case.expect == "denied"
            elif e.code == ErrorCode.PLAN_INVALID:
                ok = case.expect == "invalid"
            else:
                ok = False
            return ok, scores, e.code.value