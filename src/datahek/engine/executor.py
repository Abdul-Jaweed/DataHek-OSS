"""Engine executor — capabilities → guardrails → provider → normalized result."""
from dataclasses import dataclass, field
from typing import Any

from datahek.contracts.connections import Connection
from datahek.contracts.guardrails import GuardrailResult
from datahek.contracts.providers import DataProvider
from datahek.engine.guardrails import GuardrailPipeline, PlanComplexityGuardrail, PlanReadOnlyGuardrail
from datahek.engine.plan import LogicalPlan
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, DataProvider] = {}

    def register(self, provider: DataProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> DataProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unsupported provider: {provider_id}")
        return self._providers[provider_id]


@dataclass
class ExecutionInfo:
    provider_id: str
    duration_ms: int = 0
    compiled_query: str | None = None


@dataclass
class QueryResult:
    columns: list[dict] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution: ExecutionInfo | None = None


class Engine:
    def __init__(self, registry: ProviderRegistry, guardrails: GuardrailPipeline | None = None):
        self.registry = registry
        self.guardrails = guardrails or GuardrailPipeline([
            PlanReadOnlyGuardrail(),
            PlanComplexityGuardrail(),
        ])

    async def execute(self, ctx: RequestContext, plan: LogicalPlan, connection: Connection) -> QueryResult:
        try:
            provider = self.registry.get(connection.provider)
        except KeyError as e:
            raise DatahekError(ErrorCode.VALIDATION, str(e)) from e

        payload: dict[str, Any] = {"plan": plan, "capabilities": provider.capabilities}
        decision: GuardrailResult = await self.guardrails.run(ctx, payload)
        if decision.decision != "ALLOW":
            raise DatahekError(ErrorCode.QUERY_DENIED, decision.reason, details={"decision": decision.decision})

        client = await provider.connect(connection)
        try:
            raw = await provider.compile_and_execute(client, plan, ctx)
        except DatahekError:
            raise
        except Exception as e:
            raise DatahekError(ErrorCode.CONNECTION_FAILED, "Query execution failed") from e
        finally:
            await provider.close(client)

        max_rows = getattr(provider.capabilities, "max_result_rows", 1000)
        rows = list(raw.get("rows", []))
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        return QueryResult(
            columns=raw.get("columns", []),
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution=ExecutionInfo(provider_id=provider.provider_id),
        )