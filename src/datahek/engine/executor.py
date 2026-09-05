"""Engine executor — schema validation → capabilities → guardrails → provider → result."""
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from datahek.contracts.audit import AuditEvent, AuditSink
from datahek.contracts.connections import Connection
from datahek.contracts.guardrails import GuardrailResult
from datahek.contracts.providers import DataProvider
from datahek.engine.guardrails import GuardrailPipeline, PlanComplexityGuardrail, PlanReadOnlyGuardrail
from datahek.engine.plan import LogicalPlan, validate_plan
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

    def ids(self) -> list[str]:
        return list(self._providers)


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


logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        registry: ProviderRegistry,
        guardrails: GuardrailPipeline | None = None,
        schema_service=None,
        audit_sink: AuditSink | None = None,
        evaluation_hook=None,
        masking_policy=None,
    ):
        self.registry = registry
        self.guardrails = guardrails or GuardrailPipeline([
            PlanReadOnlyGuardrail(),
            PlanComplexityGuardrail(),
        ])
        self.schema_service = schema_service
        self.audit_sink = audit_sink
        self.evaluation_hook = evaluation_hook
        self.masking_policy = masking_policy

    async def _audit(self, ctx: RequestContext, event: AuditEvent) -> None:
        if self.audit_sink is not None:
            await self.audit_sink.record(event)

    async def execute(self, ctx: RequestContext, plan: LogicalPlan, connection: Connection) -> QueryResult:
        try:
            provider = self.registry.get(connection.provider)
        except KeyError as e:
            raise DatahekError(ErrorCode.VALIDATION, str(e)) from e

        if self.schema_service is not None:
            catalog = await self.schema_service.get_catalog(ctx, connection, provider)
            validate_plan(plan, self.schema_service.tables(catalog), self.schema_service.columns(catalog))

        payload: dict[str, Any] = {"plan": plan, "capabilities": provider.capabilities}
        decision: GuardrailResult = await self.guardrails.run(ctx, payload)

        await self._audit(ctx, AuditEvent(
            event_type="guardrail.decision",
            actor=ctx.user_id,
            action="execute",
            resource_ref=connection.id,
            decision=decision.decision,
            policy_version=decision.policy_version,
            tenant={"org": ctx.organization_id, "project": ctx.project_id},
            payload={"guardrail": decision.reason, "plan_sources": [n.source for n in plan.nodes if hasattr(n, "source")]},
        ))
        if decision.decision != "ALLOW":
            if self.evaluation_hook is not None:
                await self.evaluation_hook.on_execution_completed(
                    ctx, plan=plan, result=None, duration_ms=0, decision=decision.decision)
            raise DatahekError(ErrorCode.QUERY_DENIED, decision.reason, details={"decision": decision.decision})

        client = await provider.connect(connection)
        started = time.monotonic()
        try:
            raw = await provider.compile_and_execute(client, plan, ctx)
        except DatahekError:
            raise
        except Exception as e:
            logger.exception("Query execution failed for provider %s", provider.provider_id)
            err = DatahekError(ErrorCode.CONNECTION_FAILED, "Query execution failed")
            if self.evaluation_hook is not None:
                await self.evaluation_hook.on_execution_completed(
                    ctx, plan=plan, result=None, duration_ms=0, decision="ALLOW", failed=True)
            await self._audit(ctx, AuditEvent(
                event_type="query.execution",
                actor=ctx.user_id,
                action="execute",
                resource_ref=connection.id,
                decision="ALLOW",
                tenant={"org": ctx.organization_id, "project": ctx.project_id},
                payload={"outcome": "failed", "error_code": err.code.value},
            ))
            raise err from e
        finally:
            await provider.close(client)

        duration_ms = int((time.monotonic() - started) * 1000)
        max_rows = getattr(provider.capabilities, "max_result_rows", 1000)
        rows = list(raw.get("rows", []))
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]

        result = QueryResult(
            columns=raw.get("columns", []),
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution=ExecutionInfo(provider_id=provider.provider_id, duration_ms=duration_ms),
        )
        if self.masking_policy is not None and self.schema_service is not None:
            catalog = await self.schema_service.get_catalog(ctx, connection, provider)
            sensitive = await self.masking_policy.sensitive_columns(ctx, plan, catalog)
            if sensitive:
                from datahek.engine.masking import mask_result
                result = mask_result(result, sensitive)

        if self.evaluation_hook is not None:
            await self.evaluation_hook.on_execution_completed(
                ctx, plan=plan, result=result, duration_ms=duration_ms, decision="ALLOW")

        await self._audit(ctx, AuditEvent(
            event_type="query.execution",
            actor=ctx.user_id,
            action="execute",
            resource_ref=connection.id,
            decision="ALLOW",
            tenant={"org": ctx.organization_id, "project": ctx.project_id},
            payload={
                "outcome": "completed",
                "provider": provider.provider_id,
                "plan_sources": [n.source for n in plan.nodes if hasattr(n, "source")],
                "row_count": len(rows),
                "truncated": truncated,
                "duration_ms": duration_ms,
            },
        ))
        return result