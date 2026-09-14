"""Engine executor — schema validation → capabilities → guardrails → provider → result."""
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from datahek.contracts.audit import AuditEvent, AuditSink
from datahek.contracts.connections import Connection
from datahek.contracts.guardrails import GuardrailResult
from datahek.contracts.providers import DataProvider
from datahek.contracts.secrets import SecretRef, SecretsProvider
from datahek.engine.guardrails import (GuardrailPipeline, InputGuardrail, PlanComplexityGuardrail,
                                        PlanReadOnlyGuardrail, PolicyGuardrail, RateLimitGuardrail)
from datahek.contracts.misc import ApprovalRequest, ApprovalService
from datahek.contracts.policy import PolicyEngine
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


async def _resolve_secrets(connection: Connection, secrets: SecretsProvider) -> Connection:
    """Replace ``secret://<provider>/<path>/<key>`` settings values at connect time.

    The ref name carries the full remainder after the provider, so providers
    (e.g. Infisical) can derive the secret path from it.
    """
    resolved = dict(connection.settings)
    changed = False
    for k, v in resolved.items():
        if isinstance(v, str) and v.startswith("secret://"):
            remainder = v[len("secret://"):]
            if "/" not in remainder:
                raise DatahekError(ErrorCode.VALIDATION, "Invalid secret reference")
            provider, rest = remainder.split("/", 1)
            path, _, key = rest.rpartition("/")
            val = await secrets.get_secret(SecretRef(provider=provider, name=rest))
            resolved[k] = val.value
            changed = True
    if not changed:
        return connection
    from dataclasses import replace
    return replace(connection, settings=resolved)


class Engine:
    def __init__(
        self,
        registry: ProviderRegistry,
        guardrails: GuardrailPipeline | None = None,
        schema_service=None,
        audit_sink: AuditSink | None = None,
        evaluation_hook=None,
        masking_policy=None,
        secrets: SecretsProvider | None = None,
        policy: PolicyEngine | None = None,
        approvals: ApprovalService | None = None,
        rate_limit: int | None = None,
    ):
        self.registry = registry
        rate_guardrails = []
        if rate_limit is not None:
            from datahek.defaults.rate_limit import LocalRateLimiter

            rate_guardrails = [RateLimitGuardrail(LocalRateLimiter(), limit=rate_limit)]
        self.guardrails = guardrails or GuardrailPipeline(
            [InputGuardrail()]
            + rate_guardrails
            + ([PolicyGuardrail(policy)] if policy is not None else [])
            + [PlanReadOnlyGuardrail(), PlanComplexityGuardrail()]
        )
        self.schema_service = schema_service
        self.audit_sink = audit_sink
        self.evaluation_hook = evaluation_hook
        self.masking_policy = masking_policy
        self.secrets = secrets
        self.approvals = approvals

    async def _audit(self, ctx: RequestContext, event: AuditEvent) -> None:
        if self.audit_sink is not None:
            await self.audit_sink.record(event)

    async def execute(self, ctx: RequestContext, plan: LogicalPlan, connection: Connection) -> QueryResult:
        try:
            provider = self.registry.get(connection.provider)
        except KeyError as e:
            raise DatahekError(ErrorCode.VALIDATION, str(e)) from e

        if self.secrets is not None:
            connection = await _resolve_secrets(connection, self.secrets)

        if self.schema_service is not None:
            catalog = await self.schema_service.get_catalog(ctx, connection, provider)
            validate_plan(plan, self.schema_service.tables(catalog), self.schema_service.columns(catalog),
                          dialect=provider.capabilities.dialect)

        payload: dict[str, Any] = {"plan": plan, "capabilities": provider.capabilities,
                                   "question": getattr(ctx, "question", None)}
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
        approved = False
        if decision.decision == "REQUIRE_APPROVAL":
            if self.approvals is not None and ctx.approval_id:
                from datahek.defaults.approvals import LocalApprovalService  # noqa: F401 (documents expected impl surface)

                status = await self.approvals.status(ctx.approval_id)
                if status == "approved":
                    consume = getattr(self.approvals, "consume", None)
                    if consume is not None:
                        await consume(ctx.approval_id)
                    approved = True
                elif status == "rejected":
                    raise DatahekError(ErrorCode.QUERY_DENIED, "Approval was rejected",
                                       details={"approval_id": ctx.approval_id})
            if not approved:
                approval_id = None
                if self.approvals is not None:
                    from datahek.kernel.ids import entity_id

                    approval_id = await self.approvals.request_approval(ctx, ApprovalRequest(
                        id=entity_id("approval"),
                        org_id=ctx.organization_id,
                        project_id=ctx.project_id,
                        resource_ref=connection.id,
                        requester=ctx.user_id,
                        reason=decision.reason,
                    ))
                raise DatahekError(
                    ErrorCode.APPROVAL_REQUIRED,
                    decision.reason,
                    details={"decision": decision.decision, "approval_id": approval_id},
                )

        if decision.decision != "ALLOW" and not approved:
            if self.evaluation_hook is not None:
                await self.evaluation_hook.on_execution_completed(
                    ctx, plan=plan, result=None, duration_ms=0, decision=decision.decision)
            if decision.decision == "RATE_LIMIT":
                raise DatahekError(ErrorCode.RATE_LIMITED, decision.reason,
                                   details={"decision": decision.decision})
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