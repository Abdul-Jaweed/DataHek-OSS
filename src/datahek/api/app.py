"""DataHek OSS API — the platform's REST surface (health, connections, ask, conversations, evaluations)."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datahek import __version__
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.reasoner import Reasoner
from datahek.contracts.saved import SavedQueryStore
from datahek.contracts.verifier import Verifier
from datahek.engine.analyst import MultiStepAnalyst
from datahek.engine.suggestions import FollowUpSuggester
from datahek.defaults.guardrails import sanitize_output
from datahek.contracts.models import ModelProvider
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.context.jobs.rebuild_queue import ContextRebuildQueue
from datahek.engine.schema import SchemaService
from datahek.kernel.capabilities import OSS_CAPABILITIES
from datahek.kernel.context import RequestContext
from datahek.kernel.entitlements import EntitlementProvider
from datahek.kernel.errors import DatahekError, ErrorCode

try:
    from datahek.defaults.pg import PgMetadata
except ImportError:  # optional extra; metadata absent → PG wiring disabled
    PgMetadata = None

try:
    from datahek.defaults.redis_llm import RedisLlmSettingsStore
except ImportError:  # optional extra; store absent → behavior unchanged
    RedisLlmSettingsStore = None

logger = logging.getLogger("datahek.api")

_STATUS_BY_CODE = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONNECTION_NOT_FOUND: 404,
    ErrorCode.CONVERSATION_NOT_FOUND: 404,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.QUERY_DENIED: 422,
    ErrorCode.APPROVAL_REQUIRED: 202,
    ErrorCode.PLAN_INVALID: 422,
    ErrorCode.VALIDATION: 422,
    ErrorCode.CONNECTION_EXISTS: 409,
    ErrorCode.UNSUPPORTED_PROVIDER: 400,
    ErrorCode.CONNECTION_FAILED: 502,
    ErrorCode.QUERY_FAILED: 422,
    ErrorCode.MODEL_UNAVAILABLE: 502,
    ErrorCode.QUERY_TIMEOUT: 504,
    ErrorCode.CONTEXT_UNAVAILABLE: 503,
    ErrorCode.RATE_LIMITED: 429,
}


class ConnectionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    provider: str = Field(..., min_length=1)
    host: str | None = None
    port: int | None = Field(None, ge=1, le=65535)
    database: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class LlmSettingsRequest(BaseModel):
    base_url: str | None = Field(None, max_length=512)
    api_key: str | None = Field(None, max_length=512)
    model: str | None = Field(None, max_length=128)


class ConversationRequest(BaseModel):
    title: str | None = Field(None, max_length=200)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10_000)
    connection_id: str = Field(..., min_length=1)
    user_id: str = "anonymous"
    conversation_id: str | None = None
    prompt_id: str | None = None
    approval_id: str | None = None


class SavedQueryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    question: str = Field(..., min_length=1, max_length=10_000)
    connection_id: str = Field(..., min_length=1)


class ScheduleRequest(BaseModel):
    saved_query_id: str = Field(..., min_length=1)
    interval_seconds: int = Field(..., ge=1, le=86400 * 7)


class MetricRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    table: str = Field(..., min_length=1, max_length=128)
    aggregate: str = Field(..., min_length=1, max_length=32)
    column: str = Field("*", max_length=128)
    filter: str | None = Field(None, max_length=500)
    description: str = Field("", max_length=300)


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    actor: str = Field("anonymous", max_length=128)


class PromptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=4_000)


class ContextBuildRequest(BaseModel):
    enrichment: bool = False
    scope: str = Field("connection", pattern="^(connection|schema|table)$")
    tables: list[str] | None = Field(None, max_length=64)


class ContextPreviewRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10_000)
    budget_tokens: int | None = Field(None, ge=100, le=200_000)
    persist: bool = False


class ContextDecisionRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=32)
    index: int = Field(..., ge=0)
    action: str = Field(..., pattern="^(approve|edit|reject)$")
    section: str = Field("", max_length=32)
    patch: dict[str, Any] | None = None


class ContextValidateRequest(BaseModel):
    decisions: list[ContextDecisionRequest] = Field(..., min_length=1)


def _json_safe(value: Any) -> Any:
    """Coerce driver values (datetime, date, Decimal, bytes) to JSON-safe types."""
    import datetime as _dt
    from decimal import Decimal

    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _request_context(req, identity=None) -> RequestContext:
    """Normalized request context — carries identity when authentication is on (ADR-004)."""
    approval_id = getattr(req, "approval_id", None)
    question = getattr(req, "question", None)
    if identity is not None and identity.authenticated:
        return RequestContext(
            source="api",
            user_id=identity.user_id,
            organization_id=getattr(identity, "organization_id", "") or "default",
            authenticated=True,
            roles=identity.roles,
            permissions=identity.permissions,
            approval_id=approval_id,
            question=question,
        )
    return RequestContext(source="api", user_id=getattr(req, "user_id", "anonymous"),
                          approval_id=approval_id, question=question)


async def _conversation_history(conversations, ctx, conversation_id: str | None,
                                limit: int = 6) -> list[dict] | None:
    """Recent turns for planner context (best-effort; never fails a request)."""
    if conversations is None or not conversation_id:
        return None
    try:
        conv = await conversations.get(ctx, conversation_id)
        if conv is None:
            return None
        messages = conv.get("messages") or []
        return messages[-limit:] if messages else None
    except Exception:
        return None


async def _save_checkpoint(c, ctx, req, plan, result, decision="ALLOW") -> None:
    """Persist a per-run checkpoint for inspection/replay (best-effort)."""
    from datahek.contracts.misc import CheckpointStore

    if not c.has(CheckpointStore):
        return
    try:
        from datahek.engine.compile import compile_sql

        store = c.resolve(CheckpointStore)
        await store.save(ctx, {
            "question": req.question,
            "connection_id": req.connection_id,
            "conversation_id": req.conversation_id,
            "plan": plan.to_dict(),
            "sql": compile_sql(plan),
            "row_count": getattr(result, "row_count", None),
            "decision": decision,
        })
    except Exception as exc:  # never fail a request because a checkpoint write failed
        import logging

        logging.getLogger("datahek.api").warning("Checkpoint save failed: %s", exc)


async def _audit_output_redactions(c, ctx, connection, categories: list[str]) -> None:
    """Record output-scan redactions in the audit trail (best-effort)."""
    from datahek.contracts.audit import AuditEvent, AuditSink

    if not c.has(AuditSink):
        return
    try:
        await c.resolve(AuditSink).record(AuditEvent(
            event_type="guardrail.output",
            actor=ctx.user_id,
            action="redact",
            resource_ref=connection.id,
            decision="REDACT",
            tenant={"org": ctx.organization_id, "project": ctx.project_id},
            payload={"categories": categories},
        ))
    except Exception as exc:
        import logging

        logging.getLogger("datahek.api").warning("Output redaction audit failed: %s", exc)


async def _audit_event(c, event_type: str, action: str, actor: str = "anonymous",
                       resource_ref: str | None = None, decision: str = "ALLOW",
                       payload: dict | None = None) -> None:
    """Record a platform audit event (best-effort)."""
    from datahek.contracts.audit import AuditEvent, AuditSink

    if not c.has(AuditSink):
        return
    try:
        await c.resolve(AuditSink).record(AuditEvent(
            event_type=event_type,
            actor=actor,
            action=action,
            resource_ref=resource_ref,
            decision=decision,
            payload=payload or {},
        ))
    except Exception as exc:
        logger.warning("Audit write failed (%s/%s): %s", event_type, action, exc)


def _actor(identity) -> str:
    """Audit actor: authenticated user id, else anonymous."""
    return identity.user_id if identity is not None and identity.authenticated else "anonymous"


def _validate_aggregate(aggregate: str) -> None:
    from datahek.engine.plan import _DEFAULT_FUNCTIONS

    if aggregate not in _DEFAULT_FUNCTIONS:
        raise DatahekError(
            ErrorCode.VALIDATION,
            f"Aggregate '{aggregate}' is not supported",
            details={"allowed": sorted(_DEFAULT_FUNCTIONS)},
        )


def _suggestions_enabled() -> bool:
    import os

    return os.environ.get("DATAHEK_SUGGESTIONS", "off").lower() in ("on", "1", "true")


def _analyst_enabled() -> bool:
    import os

    return os.environ.get("DATAHEK_ANALYST", "on").lower() not in ("off", "0", "false")


def _verifier_enabled() -> bool:
    import os

    return os.environ.get("DATAHEK_VERIFIER", "on").lower() not in ("off", "0", "false")


def create_app(container=None) -> FastAPI:
    """Build the FastAPI app. ``container`` injectable for tests/Enterprise."""
    from datahek.defaults.container import build_app_container

    c = container or build_app_container()

    async def _record_turn(conversations, ctx, req, content, message_type):
        if req.conversation_id and conversations is not None:
            await conversations.append_message(ctx, req.conversation_id,
                                               {"role": "user", "content": req.question, "message_type": "question"})
            if message_type == "result" and content is None:
                content = "[streamed result]"
            await conversations.append_message(ctx, req.conversation_id, {
                "role": "assistant", "content": content, "message_type": message_type,
            })

    async def _prompt_content(req):
        from datahek.contracts.prompts import PromptStore

        if not req.prompt_id or not c.has(PromptStore):
            return None
        tpl = await c.resolve(PromptStore).get(RequestContext(source="api"), req.prompt_id)
        if tpl is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Prompt '{req.prompt_id}' not found")
        return tpl["content"]

    async def _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner, identity=None):
        from datahek.contracts.misc import ConversationStore
        from datahek.contracts.prompts import PromptStore

        ctx = _request_context(req, identity)
        conn = await conn_mgr.get_connection(ctx, req.connection_id)
        provider = registry.get(conn.provider)

        conversations: ConversationStore | None = c.resolve(ConversationStore) if c.has(ConversationStore) else None
        if req.conversation_id and conversations is not None:
            existing = await conversations.get(ctx, req.conversation_id)
            if existing is None:
                raise DatahekError(
                    ErrorCode.CONVERSATION_NOT_FOUND,
                    f"Conversation '{req.conversation_id}' not found",
                    details={"conversation_id": req.conversation_id},
                )

        extra_prompt = None
        if req.prompt_id and c.has(PromptStore):
            tpl = await c.resolve(PromptStore).get(ctx, req.prompt_id)
            if tpl is None:
                raise DatahekError(ErrorCode.NOT_FOUND, f"Prompt '{req.prompt_id}' not found")
            extra_prompt = tpl["content"]

        history = await _conversation_history(conversations, ctx, req.conversation_id)
        analyst = c.resolve(MultiStepAnalyst) if c.has(MultiStepAnalyst) else None
        if (analyst is not None and _analyst_enabled()
                and MultiStepAnalyst.looks_complex(req.question)):
            try:
                multi = await analyst.run(req.question, ctx, conn, provider, history=history)
            except DatahekError:
                raise
            except Exception as exc:
                logger.warning("Multi-step analysis failed; falling back to single step: %s", exc)
                multi = None
            if multi is not None:
                step_results, synthesis = multi
                synthesis, step_redactions = sanitize_output(synthesis)
                if step_redactions:
                    await _audit_output_redactions(c, ctx, conn, step_redactions)
                await _record_turn(conversations, ctx, req, synthesis, "result")
                verification = None
                if _verifier_enabled() and c.has(Verifier):
                    verification = {"ok": True, "note": "multi-step analysis; per-step results attached"}
                return {
                    "clarification": None,
                    "answer": synthesis,
                    "rows": step_results[0].get("rows") if step_results else None,
                    "columns": step_results[0].get("columns") if step_results else None,
                    "row_count": sum(r.get("row_count") or 0 for r in step_results),
                    "truncated": False,
                    "plan_sources": [],
                    "conversation_id": req.conversation_id,
                    "steps": step_results,
                    "verification": verification,
                    "redactions": step_redactions or None,
                }

        plan_result = await planner.plan(req.question, ctx, conn, provider,
                                         extra_prompt=extra_prompt, history=history)
        if plan_result.clarification:
            await _record_turn(conversations, ctx, req, plan_result.clarification, "clarification")
            metrics.inc("datahek_ask_results_total", outcome="clarification")
            return {
                "clarification": plan_result.clarification,
                "answer": plan_result.clarification,
                "rows": None, "columns": None, "row_count": 0,
                "truncated": False, "plan_sources": [],
                "conversation_id": req.conversation_id,
            }

        result = await engine.execute(ctx, plan_result.plan, conn)
        columns = [c["name"] for c in result.columns]
        rows = [dict(zip(columns, [_json_safe(v) for v in row])) for row in result.rows]
        await _save_checkpoint(c, ctx, req, result.plan or plan_result.plan, result)

        follow_ups: dict[str, Any] = {
            "explanation": reasoner.explain(req.question, result, plan_result.plan, ctx)}
        if _verifier_enabled() and c.has(Verifier):
            follow_ups["verification"] = c.resolve(Verifier).verify(req.question, result, ctx)
        if _suggestions_enabled() and c.has(FollowUpSuggester):
            follow_ups["suggestions"] = c.resolve(FollowUpSuggester).suggest(
                req.question, result, ctx)
        outcomes = await asyncio.gather(*follow_ups.values(), return_exceptions=True)
        gathered = dict(zip(follow_ups, outcomes))
        explanation = gathered["explanation"]
        if isinstance(explanation, BaseException):
            raise explanation
        verification = gathered.get("verification")
        if isinstance(verification, BaseException):
            logger.warning("Verifier unavailable: %s", verification)
            verification = None
        suggestions = gathered.get("suggestions")
        if isinstance(suggestions, BaseException):
            logger.warning("Follow-up suggestions unavailable: %s", suggestions)
            suggestions = None
        explanation, redactions = sanitize_output(explanation)
        if redactions:
            await _audit_output_redactions(c, ctx, conn, redactions)
        await _record_turn(conversations, ctx, req, explanation, "result")
        metrics.inc("datahek_ask_results_total", outcome="ok")
        metrics.inc("datahek_rows_returned_total", result.row_count or 0)
        return {
            "suggestions": suggestions or None,
            "verification": verification,
            "redactions": redactions or None,
            "clarification": None,
            "answer": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "plan_sources": plan_result.sources_used,
            "conversation_id": req.conversation_id,
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if PgMetadata is not None and c.has(PgMetadata):
            pg = c.resolve(PgMetadata)
            if pg is not None and getattr(pg, "_url", None):
                await pg.init_schema()
        if RedisLlmSettingsStore is not None and c.has(RedisLlmSettingsStore):
            reload = getattr(model_provider, "reload_from_store", None)
            if reload is not None:
                try:
                    await reload()
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "LLM settings reload from Redis failed (%s); continuing with env config", exc)

        rebuild_queue = None
        if c.has(ContextRebuildQueue):
            rebuild_queue = c.resolve(ContextRebuildQueue)
            await rebuild_queue.start()

        scheduler = None
        if c.has(SavedQueryStore):
            from datahek.defaults.scheduler import LocalScheduler

            async def _scheduled_run(run_ctx, schedule):
                saved = await c.resolve(SavedQueryStore).get(run_ctx, schedule["saved_query_id"])
                if saved is None:
                    return {"status": "error", "detail": "saved query missing"}
                req = AskRequest(question=saved["question"], connection_id=saved["connection_id"])
                try:
                    answer = await _ask_pipeline(req, c, conn_mgr, registry, planner, engine,
                                                 reasoner)
                except Exception as exc:
                    return {"status": "error", "detail": str(exc)[:200]}
                if answer.get("clarification"):
                    return {"status": "clarification", "detail": answer["clarification"][:200]}
                return {"status": "ok", "rows": answer.get("row_count"),
                        "detail": f"{answer.get('row_count', 0)} rows"}

            scheduler = LocalScheduler(
                store=c.resolve(SavedQueryStore),
                runner=_scheduled_run,
                poll_seconds=float(os.environ.get("DATAHEK_SCHEDULER_POLL_SECONDS", "30")),
            )
            await scheduler.start(RequestContext(source="scheduler"))
        yield
        if scheduler is not None:
            await scheduler.stop()
        if rebuild_queue is not None:
            await rebuild_queue.stop()

    from datahek.defaults.log_setup import configure_logging

    configure_logging()

    app = FastAPI(title="DataHek OSS", version=__version__, lifespan=lifespan)

    from datahek.defaults.metrics import LocalMetrics

    metrics: LocalMetrics = c.resolve(LocalMetrics)

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        import time as _time

        started = _time.perf_counter()
        response = await call_next(request)
        elapsed = _time.perf_counter() - started
        route = request.scope.get("route")
        endpoint = getattr(route, "path", request.url.path)
        if endpoint.startswith("/metrics"):
            return response
        metrics.inc("datahek_requests_total", endpoint=endpoint, status=response.status_code)
        metrics.observe("datahek_request_duration_seconds", elapsed, endpoint=endpoint)
        return response
    conn_mgr: ConnectionManager = c.resolve(ConnectionManager)
    registry: ProviderRegistry = c.resolve(ProviderRegistry)
    planner: Planner = c.resolve(Planner)
    engine: Engine = c.resolve(Engine)
    entitlements: EntitlementProvider = c.resolve(EntitlementProvider)
    reasoner = c.resolve(Reasoner)
    model_provider: ModelProvider = c.resolve(ModelProvider)

    from datahek.defaults.auth import AuthConfig, LocalAuthProvider
    auth_config: AuthConfig = c.resolve(AuthConfig) if c.has(AuthConfig) else AuthConfig()
    auth_provider: AuthProvider = c.resolve(AuthProvider)

    async def _require_auth(request: Request):
        if auth_config.mode != "local":
            return None
        token = request.headers.get("X-API-Key")
        if not token:
            header = request.headers.get("Authorization", "")
            if header.lower().startswith("bearer "):
                token = header[7:].strip()
        if not token:
            await _audit_event(c, "auth.failure", "authenticate", decision="DENY",
                               payload={"reason": "missing_api_key", "path": request.url.path})
            raise DatahekError(ErrorCode.UNAUTHORIZED, "API key required")
        ident = await auth_provider.authenticate_api_key(token)
        if not ident.authenticated:
            await _audit_event(c, "auth.failure", "authenticate", decision="DENY",
                               payload={"reason": "invalid_api_key", "path": request.url.path})
            raise DatahekError(ErrorCode.UNAUTHORIZED, "Invalid API key")
        return ident

    @app.exception_handler(DatahekError)
    async def _datahek_error_handler(request: Request, exc: DatahekError) -> JSONResponse:
        if request.url.path.startswith("/ask"):
            try:
                metrics.inc("datahek_ask_results_total", outcome=exc.code.value.lower())
            except Exception:
                pass
        return JSONResponse(
            status_code=_STATUS_BY_CODE.get(exc.code, 400),
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        import logging
        logging.getLogger("datahek.api").exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"code": ErrorCode.INTERNAL.value, "message": "Internal server error", "details": {}},
        )

    @app.get("/audit")
    async def search_audit_endpoint(limit: int = 50, event_type: str | None = None,
                                    actor: str | None = None, decision: str | None = None,
                                    contains: str | None = None,
                                    _identity=Depends(_require_auth)):
        from datahek.defaults.audit_search import search_audit

        return search_audit(limit=min(limit, 500), event_type=event_type,
                            actor=actor, decision=decision, contains=contains)

    @app.get("/metrics")
    async def prometheus_metrics():
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "auth_mode": auth_config.mode,
            "capabilities": {
                name: OSS_CAPABILITIES.supports(name)
                for name in ("sso", "multi_tenancy", "advanced_rbac", "policy_engine",
                             "centralized_audit", "usage_analytics", "high_availability")
            },
            "entitlements": entitlements.all_limits(),
            "providers": registry.ids(),
        }

    @app.get("/connections/{connection_id}/context")
    async def get_connection_context(request: Request, connection_id: str,
                                     scope: str = "connection",
                                     _identity=Depends(_require_auth)):
        from datahek.context.registry import ContextRegistryService
        from datahek.context.serialization import record_to_dict

        record = await c.resolve(ContextRegistryService).active(
            _request_context(request, _identity), connection_id=connection_id,
            scope=scope)
        return {"context": record_to_dict(record) if record is not None else None}

    @app.get("/connections/{connection_id}/context/versions")
    async def get_connection_context_versions(request: Request, connection_id: str,
                                              limit: int = 20, scope: str = "connection",
                                              _identity=Depends(_require_auth)):
        from datahek.contracts.context import ContextRegistry
        from datahek.context.serialization import record_to_dict

        records = await c.resolve(ContextRegistry).versions(
            _request_context(request, _identity), connection_id=connection_id, scope=scope)
        newest = sorted(records, key=lambda record: record.version, reverse=True)
        return {"versions": [record_to_dict(record)
                             for record in newest[:min(max(limit, 1), 100)]]}

    @app.get("/connections/{connection_id}/context/pending")
    async def get_connection_context_pending(request: Request, connection_id: str,
                                             scope: str = "connection",
                                             _identity=Depends(_require_auth)):
        from dataclasses import asdict

        from datahek.context.validation import ContextValidationService

        items = await c.resolve(ContextValidationService).list_pending(
            _request_context(request, _identity), connection_id=connection_id, scope=scope)
        return {"items": [asdict(item) for item in items]}

    @app.post("/connections/{connection_id}/context/validate")
    async def validate_connection_context(request: Request, connection_id: str,
                                          req: ContextValidateRequest,
                                          scope: str = "connection",
                                          _identity=Depends(_require_auth)):
        from datahek.contracts.context import ArtifactKind
        from datahek.context.serialization import record_to_dict
        from datahek.context.validation import ContextValidationService, ValidationDecision

        decisions = []
        for item in req.decisions:
            try:
                kind = ArtifactKind(item.kind)
            except ValueError as exc:
                raise DatahekError(
                    ErrorCode.VALIDATION,
                    f"Unknown artifact kind '{item.kind}'") from exc
            decisions.append(ValidationDecision(kind, item.index, item.action,
                                                section=item.section, patch=item.patch))
        try:
            record = await c.resolve(ContextValidationService).apply(
                _request_context(request, _identity), connection_id=connection_id,
                decisions=tuple(decisions), scope=scope)
        except Exception:
            metrics.inc("datahek_context_validations_total", outcome="error")
            raise
        metrics.inc("datahek_context_validations_total", outcome="published")
        await _audit_event(c, "context.validate", "validate", actor=_actor(_identity),
                           resource_ref=record.context_id,
                           payload={"connection": connection_id,
                                    "decisions": len(decisions)})
        return {"context": record_to_dict(record)}

    @app.post("/connections/{connection_id}/context/preview")
    async def preview_connection_context(request: Request, connection_id: str,
                                         req: ContextPreviewRequest,
                                         scope: str = "connection",
                                         _identity=Depends(_require_auth)):
        from datahek.contracts.context import (
            ContextCompiler,
            ContextComposer,
            ContextRetriever,
            RuntimeContext,
        )

        ctx = _request_context(request, _identity)
        started = time.perf_counter()
        rebuild_job = None
        try:
            retrieved = await c.resolve(ContextRetriever).retrieve(
                ctx, connection_id=connection_id, question=req.question, scope=scope)
            if retrieved is None:
                metrics.inc("datahek_context_retrievals_total", outcome="miss")
                raise DatahekError(ErrorCode.NOT_FOUND,
                                   f"No active context for connection '{connection_id}'")
            composed = await c.resolve(ContextComposer).compose(
                ctx, retrieved, RuntimeContext(question=req.question),
                budget_tokens=req.budget_tokens)
            package = await c.resolve(ContextCompiler).compile(
                ctx, composed, quality=retrieved.quality, freshness=retrieved.freshness)
        except DatahekError:
            raise
        except Exception as exc:
            metrics.inc("datahek_context_retrievals_total", outcome="error")
            raise DatahekError(ErrorCode.CONTEXT_UNAVAILABLE, "Context layer unavailable",
                               details={"reason": str(exc)[:200]}) from exc
        metrics.observe("datahek_context_retrieval_duration_seconds",
                        time.perf_counter() - started)
        insufficient = package.quality.details.get("insufficient_reason", "")
        metrics.inc("datahek_context_retrievals_total",
                    outcome="insufficient" if insufficient else "hit")
        if insufficient:
            metrics.inc("datahek_context_insufficient_total")
        metrics.observe("datahek_context_tokens", float(package.budget.tokens_estimate))
        from datahek.context.jobs.rebuild_queue import maybe_enqueue_rebuild

        auto_rebuild = os.environ.get("DATAHEK_CONTEXT_AUTO_REBUILD", "off").lower()             in ("on", "1", "true")
        rebuild_job = await maybe_enqueue_rebuild(
            c.resolve(ContextRebuildQueue) if c.has(ContextRebuildQueue) else None,
            ctx, connection_id, scope, retrieved.stale, auto_rebuild)
        persisted = False
        if req.persist:
            from datahek.contracts.context import ContextStore

            await c.resolve(ContextStore).put_package(ctx, package.context_id, package)
            persisted = True
        return {
            "rebuild_job": rebuild_job,
            "persisted": persisted,
            "context_id": package.context_id,
            "version": package.version,
            "schema_hash": package.schema_hash,
            "stale": retrieved.stale,
            "tables": [{"name": table.name, "columns": len(table.columns)}
                       for table in package.schema],
            "metrics": [str(metric.get("name", "")) for metric in package.semantics.metrics],
            "tokens": package.budget.tokens_estimate,
            "dropped": list(package.degraded),
            "insufficient": insufficient,
            "trust": package.trust.value,
            "quality": package.quality.state.value,
        }

    @app.post("/connections/{connection_id}/context/build")
    async def build_connection_context(request: Request, connection_id: str,
                                       req: ContextBuildRequest,
                                       _identity=Depends(_require_auth)):
        from dataclasses import asdict

        from datahek.context.jobs.build_context import ContextBuildJob

        ctx = _request_context(request, _identity)
        connection = await conn_mgr.get_connection(ctx, connection_id)
        provider = registry.get(connection.provider)
        started = time.perf_counter()
        try:
            result = await c.resolve(ContextBuildJob).run(
                ctx, connection, provider, enrichment=req.enrichment,
                tables=req.tables, scope=req.scope)
        except Exception:
            metrics.inc("datahek_context_builds_total", outcome="error")
            raise
        metrics.observe("datahek_context_build_duration_seconds",
                        time.perf_counter() - started)
        metrics.inc("datahek_context_builds_total", outcome=result.state)
        await _audit_event(c, "context.build", "build", actor=_actor(_identity),
                           resource_ref=result.context_id or connection_id,
                           payload={"connection": connection_id, "state": result.state,
                                    "enrichment": req.enrichment, "scope": req.scope,
                                    "tables": req.tables})
        return asdict(result)

    @app.get("/contexts/{context_id}")
    async def get_context_record(request: Request, context_id: str,
                                 _identity=Depends(_require_auth)):
        from datahek.contracts.context import ContextRegistry
        from datahek.context.serialization import record_to_dict

        record = await c.resolve(ContextRegistry).get(
            _request_context(request, _identity), context_id)
        if record is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Context '{context_id}' not found")
        return {"context": record_to_dict(record),
                "artifact_kinds": [kind.value for kind in record.artifact_kinds]}

    @app.post("/connections/{connection_id}/context/rebuild", status_code=202)
    async def rebuild_connection_context(request: Request, connection_id: str,
                                         enrichment: bool = False, scope: str = "connection",
                                         _identity=Depends(_require_auth)):
        if not c.has(ContextRebuildQueue):
            raise DatahekError(ErrorCode.CONTEXT_UNAVAILABLE,
                               "Context rebuild queue is not configured")
        job = await c.resolve(ContextRebuildQueue).enqueue(
            _request_context(request, _identity), connection_id, scope=scope,
            enrichment=enrichment)
        await _audit_event(c, "context.rebuild", "enqueue", actor=_actor(_identity),
                           resource_ref=connection_id,
                           payload={"job": job["id"], "enrichment": enrichment})
        return job

    @app.get("/context/rebuilds")
    async def list_context_rebuilds(request: Request, job_id: str | None = None,
                                    _identity=Depends(_require_auth)):
        if not c.has(ContextRebuildQueue):
            raise DatahekError(ErrorCode.CONTEXT_UNAVAILABLE,
                               "Context rebuild queue is not configured")
        ctx = _request_context(request, _identity)
        return {"jobs": c.resolve(ContextRebuildQueue).status(
            job_id=job_id, org_id=ctx.organization_id)}

    @app.get("/contexts/{context_id}/package")
    async def get_context_package(request: Request, context_id: str,
                                  _identity=Depends(_require_auth)):
        from datahek.contracts.context import ContextStore
        from datahek.context.serialization import package_to_dict

        package = await c.resolve(ContextStore).get_package(
            _request_context(request, _identity), context_id)
        if package is None:
            raise DatahekError(ErrorCode.NOT_FOUND,
                               f"No persisted package for context '{context_id}'")
        return {"package": package_to_dict(package)}

    @app.post("/auth/login")
    async def auth_login(req: LoginRequest, _identity=None):
        """Local login: returns the API token for subsequent requests (X-API-Key)."""
        ident = await auth_provider.authenticate(req.username, req.password)
        if not ident.authenticated:
            await _audit_event(c, "auth.failure", "login", actor=req.username, decision="DENY",
                               payload={"reason": "invalid_credentials"})
            raise DatahekError(ErrorCode.UNAUTHORIZED, "Invalid username or password")
        return {
            "token": req.password,
            "user": ident.user_id,
            "roles": sorted(ident.roles),
            "provider": ident.provider,
        }

    @app.get("/settings/llm")
    async def get_llm_settings(_identity=Depends(_require_auth)):
        return await model_provider.describe()

    @app.post("/settings/llm")
    async def set_llm_settings(req: LlmSettingsRequest, _identity=Depends(_require_auth)):
        await model_provider.configure(**req.model_dump(exclude_none=True))
        if RedisLlmSettingsStore is not None and c.has(RedisLlmSettingsStore):
            try:
                await c.resolve(RedisLlmSettingsStore).save(req.model_dump(exclude_none=True))
            except Exception as exc:
                import logging
                logging.getLogger("datahek.api").warning(
                    "Failed to persist LLM settings to store: %s", exc
                )
        return await model_provider.describe()

    @app.post("/connections", status_code=201)
    async def create_connection(request: Request, req: ConnectionRequest,
                                _identity=Depends(_require_auth)):
        from datahek.contracts.connections import Connection
        from datahek.kernel.ids import entity_id

        if req.provider not in registry.ids():
            raise DatahekError(
                ErrorCode.UNSUPPORTED_PROVIDER,
                f"Provider '{req.provider}' is not supported",
                details={"provider": req.provider},
            )
        ctx = _request_context(req, _identity)
        current = len(await conn_mgr.list_connections(ctx))
        limit = entitlements.limit("connections")
        if limit is not None and current >= limit:
            raise DatahekError(
                ErrorCode.RATE_LIMITED,
                f"Connection limit reached ({limit})",
                details={"resource": "connections", "limit": limit, "current": current},
            )
        conn = Connection(
            id=entity_id("connection"),
            name=req.name,
            provider=req.provider,
            org_id=ctx.organization_id,
            project_id=ctx.project_id,
            host=req.host,
            port=req.port,
            database=req.database,
            settings=req.settings,
        )
        await conn_mgr.add(ctx, conn)
        await _audit_event(c, "connection.create", "create", actor=_actor(_identity),
                           resource_ref=conn.id, payload={"provider": conn.provider, "name": conn.name})
        return {
            "id": conn.id, "name": conn.name, "provider": conn.provider,
            "host": conn.host, "port": conn.port, "database": conn.database,
        }

    @app.get("/connections")
    async def list_connections(request: Request, _identity=Depends(_require_auth)):
        ctx = _request_context(request, _identity)
        conns = await conn_mgr.list_connections(ctx)
        return [{
            "id": c.id, "name": c.name, "provider": c.provider,
            "host": c.host, "port": c.port, "database": c.database,
        } for c in conns]

    @app.post("/connections/test")
    async def test_connection(request: Request, req: ConnectionRequest,
                              _identity=Depends(_require_auth)):
        """Test connectivity for the values as-entered (nothing persisted)."""
        from datahek.contracts.connections import Connection

        if req.provider not in registry.ids():
            raise DatahekError(
                ErrorCode.UNSUPPORTED_PROVIDER,
                f"Provider '{req.provider}' is not supported",
                details={"provider": req.provider},
            )
        ctx = RequestContext(source="api")
        conn = Connection(
            id="probe", name=req.name or "probe", provider=req.provider,
            org_id=ctx.organization_id, project_id=ctx.project_id,
            host=req.host, port=req.port, database=req.database,
            settings=req.settings,
        )
        provider = registry.get(conn.provider)
        start = time.perf_counter()
        try:
            client = await provider.connect(conn)
            await provider.introspect(ctx, conn, f"{conn.id}:{conn.database}")
            if hasattr(client, "close"):
                try:
                    client.close()
                except Exception:
                    pass
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": str(exc)[:500],
            }

    @app.put("/connections/{connection_id}")
    async def update_connection(request: Request, connection_id: str, req: ConnectionRequest,
                                _identity=Depends(_require_auth)):
        ctx = _request_context(req, _identity)
        if req.provider not in registry.ids():
            raise DatahekError(
                ErrorCode.UNSUPPORTED_PROVIDER,
                f"Provider '{req.provider}' is not supported",
                details={"provider": req.provider},
            )
        patch = {
            "name": req.name, "provider": req.provider,
            "host": req.host, "port": req.port, "database": req.database,
        }
        if req.settings:
            existing = await conn_mgr.get_connection(ctx, connection_id)
            patch["settings"] = {**existing.settings, **req.settings}
        updated = await conn_mgr.update(ctx, connection_id, patch)
        await _audit_event(c, "connection.update", "update", actor=_actor(_identity),
                           resource_ref=connection_id, payload={"provider": updated.provider})
        return {
            "id": updated.id, "name": updated.name, "provider": updated.provider,
            "host": updated.host, "port": updated.port, "database": updated.database,
        }

    @app.delete("/connections/{connection_id}", status_code=204)
    async def delete_connection(request: Request, connection_id: str,
                                _identity=Depends(_require_auth)):
        ctx = _request_context(request, _identity)
        await conn_mgr.remove(ctx, connection_id)
        await _audit_event(c, "connection.delete", "delete", actor=_actor(_identity),
                           resource_ref=connection_id)

    @app.post("/saved-queries", status_code=201)
    async def create_saved_query(req: SavedQueryRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQuery, SavedQueryStore
        from datahek.kernel.ids import entity_id

        ctx = RequestContext(source="api")
        query = SavedQuery(id=entity_id("saved"), name=req.name, question=req.question,
                           connection_id=req.connection_id,
                           org_id=ctx.organization_id, project_id=ctx.project_id)
        store = c.resolve(SavedQueryStore)
        await store.create(ctx, query)
        await _audit_event(c, "saved_query.create", "create", actor=_actor(_identity),
                           resource_ref=query.id, payload={"name": query.name})
        return await store.get(ctx, query.id)

    @app.get("/saved-queries")
    async def list_saved_queries(_identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore

        return await c.resolve(SavedQueryStore).list_queries(RequestContext(source="api"))

    @app.post("/saved-queries/{query_id}/run")
    async def run_saved_query(query_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore

        ctx = RequestContext(source="api")
        store = c.resolve(SavedQueryStore)
        saved = await store.get(ctx, query_id)
        if saved is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Saved query '{query_id}' not found")
        req = AskRequest(question=saved["question"], connection_id=saved["connection_id"])
        return await _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner,
                                   identity=_identity)

    @app.delete("/saved-queries/{query_id}", status_code=204)
    async def delete_saved_query(query_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore

        ctx = RequestContext(source="api")
        store = c.resolve(SavedQueryStore)
        if await store.get(ctx, query_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Saved query '{query_id}' not found")
        await store.delete(ctx, query_id)
        await _audit_event(c, "saved_query.delete", "delete", actor=_actor(_identity),
                           resource_ref=query_id)

    @app.post("/schedules", status_code=201)
    async def create_schedule(req: ScheduleRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore, Schedule
        from datahek.kernel.ids import entity_id

        ctx = RequestContext(source="api")
        store = c.resolve(SavedQueryStore)
        if await store.get(ctx, req.saved_query_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Saved query '{req.saved_query_id}' not found")
        schedule = Schedule(id=entity_id("sched"), saved_query_id=req.saved_query_id,
                            interval_seconds=req.interval_seconds,
                            org_id=ctx.organization_id, project_id=ctx.project_id)
        await store.create_schedule(ctx, schedule)
        await _audit_event(c, "schedule.create", "create", actor=_actor(_identity),
                           resource_ref=schedule.id,
                           payload={"saved_query_id": schedule.saved_query_id})
        return await store.get_schedule(ctx, schedule.id)

    @app.get("/schedules")
    async def list_schedules(_identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore

        return await c.resolve(SavedQueryStore).list_schedules(RequestContext(source="api"))

    @app.delete("/schedules/{schedule_id}", status_code=204)
    async def delete_schedule(schedule_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.saved import SavedQueryStore

        ctx = RequestContext(source="api")
        store = c.resolve(SavedQueryStore)
        if await store.get_schedule(ctx, schedule_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Schedule '{schedule_id}' not found")
        await store.delete_schedule(ctx, schedule_id)
        await _audit_event(c, "schedule.delete", "delete", actor=_actor(_identity),
                           resource_ref=schedule_id)

    @app.post("/checkpoints/{checkpoint_id}/fork")
    async def fork_checkpoint(checkpoint_id: str, _identity=Depends(_require_auth)):
        """Re-plan and re-run a stored question with current settings (new lineage)."""
        from datahek.contracts.misc import CheckpointStore

        ctx = RequestContext(source="api")
        store = c.resolve(CheckpointStore)
        item = await store.get(ctx, checkpoint_id)
        if item is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Checkpoint '{checkpoint_id}' not found")

        req = AskRequest(question=item["question"], connection_id=item["connection_id"],
                         conversation_id=item.get("conversation_id"))
        answer = await _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner,
                                     identity=_identity)
        # re-save the newest checkpoint with lineage (best-effort)
        try:
            newest = (await store.list(ctx, limit=1)) or [None]
            if newest and newest[0] and newest[0]["id"] != checkpoint_id:
                forked = newest[0]
                forked["forked_from"] = checkpoint_id
                await store.save(ctx, forked)
                answer["forked_from"] = checkpoint_id
                answer["new_checkpoint_id"] = forked["id"]
        except Exception:
            pass
        return answer

    @app.get("/checkpoints/{checkpoint_id}/diff/{other_id}")
    async def diff_checkpoints(checkpoint_id: str, other_id: str,
                               _identity=Depends(_require_auth)):
        """Field-level comparison of two stored runs (what changed between them)."""
        from datahek.contracts.misc import CheckpointStore

        ctx = RequestContext(source="api")
        store = c.resolve(CheckpointStore)
        left = await store.get(ctx, checkpoint_id)
        right = await store.get(ctx, other_id)
        if left is None or right is None:
            raise DatahekError(ErrorCode.NOT_FOUND, "Checkpoint not found")

        fields = ("question", "sql", "row_count", "decision", "conversation_id", "forked_from")
        changes = {
            field: {"left": left.get(field), "right": right.get(field)}
            for field in fields
            if left.get(field) != right.get(field)
        }
        return {
            "left": checkpoint_id,
            "right": other_id,
            "identical": not changes,
            "changes": changes,
        }

    @app.get("/semantics")
    async def list_metrics(_identity=Depends(_require_auth)):
        from datahek.contracts.semantics import SemanticStore

        store = c.resolve(SemanticStore)
        return await store.list(RequestContext(source="api"))

    @app.post("/semantics", status_code=201)
    async def create_metric(req: MetricRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.semantics import Metric, SemanticStore
        from datahek.kernel.ids import entity_id

        _validate_aggregate(req.aggregate)
        ctx = RequestContext(source="api")
        metric = Metric(
            id=entity_id("metric"), name=req.name, table=req.table,
            aggregate=req.aggregate, column=req.column, filter=req.filter,
            description=req.description, org_id=ctx.organization_id, project_id=ctx.project_id,
        )
        store = c.resolve(SemanticStore)
        await store.create(ctx, metric)
        await _audit_event(c, "metric.create", "create", actor=_actor(_identity),
                           resource_ref=metric.id, payload={"name": metric.name})
        return await store.get(ctx, metric.id)

    @app.put("/semantics/{metric_id}")
    async def update_metric(metric_id: str, req: MetricRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.semantics import SemanticStore

        _validate_aggregate(req.aggregate)
        ctx = RequestContext(source="api")
        store = c.resolve(SemanticStore)
        if await store.get(ctx, metric_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Metric '{metric_id}' not found")
        await store.update(ctx, metric_id, {
            "name": req.name, "table": req.table, "aggregate": req.aggregate,
            "column": req.column, "filter": req.filter, "description": req.description,
        })
        await _audit_event(c, "metric.update", "update", actor=_actor(_identity),
                           resource_ref=metric_id, payload={"name": req.name})
        return await store.get(ctx, metric_id)

    @app.delete("/semantics/{metric_id}", status_code=204)
    async def delete_metric(metric_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.semantics import SemanticStore

        ctx = RequestContext(source="api")
        store = c.resolve(SemanticStore)
        if await store.get(ctx, metric_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Metric '{metric_id}' not found")
        await store.delete(ctx, metric_id)
        await _audit_event(c, "metric.delete", "delete", actor=_actor(_identity),
                           resource_ref=metric_id)

    @app.get("/approvals")
    async def list_approvals(_identity=Depends(_require_auth)):
        from datahek.contracts.misc import ApprovalService

        if not c.has(ApprovalService):
            return []
        import inspect

        service = c.resolve(ApprovalService)
        lister = getattr(service, "list_all", None)
        if lister is None:
            return []
        result = lister()
        if inspect.isawaitable(result):
            result = await result
        return result

    @app.post("/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: str, req: ApprovalDecisionRequest,
                              _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ApprovalService

        service = c.resolve(ApprovalService)
        mapped = "approved" if req.decision == "approve" else "rejected"
        await service.decide(approval_id, mapped, req.actor)
        status = await service.status(approval_id)
        await _audit_event(c, "approval.decision", mapped, actor=req.actor,
                           resource_ref=approval_id, decision=mapped.upper(),
                           payload={"status": status})
        return {"approval_id": approval_id, "status": status}

    @app.get("/checkpoints")
    async def list_checkpoints(request: Request, limit: int = 20,
                               _identity=Depends(_require_auth)):
        from datahek.contracts.misc import CheckpointStore

        store = c.resolve(CheckpointStore)
        items = await store.list(_request_context(request, _identity), limit=min(limit, 100))
        return [{k: v for k, v in item.items() if k != "plan"} for item in items]

    @app.get("/checkpoints/{checkpoint_id}")
    async def get_checkpoint(checkpoint_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import CheckpointStore

        store = c.resolve(CheckpointStore)
        item = await store.get(RequestContext(source="api"), checkpoint_id)
        if item is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Checkpoint '{checkpoint_id}' not found")
        return item

    @app.post("/checkpoints/{checkpoint_id}/replay")
    async def replay_checkpoint(checkpoint_id: str, _identity=Depends(_require_auth)):
        """Deterministically re-execute a stored plan — no LLM involved."""
        from datahek.contracts.misc import CheckpointStore
        from datahek.engine.plan import LogicalPlan

        ctx = RequestContext(source="api")
        store = c.resolve(CheckpointStore)
        item = await store.get(ctx, checkpoint_id)
        if item is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Checkpoint '{checkpoint_id}' not found")

        plan = LogicalPlan.from_dict(item["plan"])
        if not plan.read_only:
            raise DatahekError(ErrorCode.QUERY_DENIED, "Replay blocked: stored plan is not read-only")

        conn = await conn_mgr.get_connection(ctx, item["connection_id"])
        provider = registry.get(conn.provider)
        client = await provider.connect(conn)
        try:
            raw = await provider.compile_and_execute(client, plan, ctx)
        finally:
            close = getattr(provider, "close", None)
            if close is not None:
                try:
                    await close(client)
                except Exception:
                    pass
        columns = [c["name"] for c in raw["columns"]]
        rows = [dict(zip(columns, [_json_safe(v) for v in row])) for row in raw["rows"]]
        return {
            "checkpoint_id": checkpoint_id, "replayed": True,
            "question": item["question"], "sql": item["sql"],
            "columns": columns, "rows": rows, "row_count": len(rows),
        }

    @app.post("/ask")
    async def ask(req: AskRequest, _identity=Depends(_require_auth)):
        return await _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner,
                                   identity=_identity)

    @app.post("/ask/stream")
    async def ask_stream(req: AskRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore
        from fastapi.responses import StreamingResponse
        import json as _json

        ctx = _request_context(req, _identity)
        conn = await conn_mgr.get_connection(ctx, req.connection_id)
        provider = registry.get(conn.provider)

        conversations: ConversationStore | None = c.resolve(ConversationStore) if c.has(ConversationStore) else None
        if req.conversation_id and conversations is not None:
            existing = await conversations.get(ctx, req.conversation_id)
            if existing is None:
                raise DatahekError(
                    ErrorCode.CONVERSATION_NOT_FOUND,
                    f"Conversation '{req.conversation_id}' not found",
                    details={"conversation_id": req.conversation_id},
                )

        async def gen():
            def ev(payload: dict) -> str:
                return f"data: {_json.dumps(payload)}\n\n"

            yield ev({"type": "progress", "stage": "connecting", "message": "Resolving connection and schema…"})
            yield ev({"type": "progress", "stage": "planning", "message": "Planning a validated query…"})
            try:
                if (c.has(MultiStepAnalyst) and _analyst_enabled()
                        and MultiStepAnalyst.looks_complex(req.question)):
                    analyst = c.resolve(MultiStepAnalyst)
                    yield ev({"type": "progress", "stage": "planning",
                              "message": "Decomposing into sub-questions…"})
                    multi = await analyst.run(req.question, ctx, conn, provider,
                                              history=await _conversation_history(conversations, ctx, req.conversation_id))
                    if multi is not None:
                        step_results, synthesis = multi
                        synthesis, stream_redactions = sanitize_output(synthesis)
                        first = step_results[0] if step_results else {}
                        steps_meta = [{"question": r["question"], "row_count": r.get("row_count"),
                                       "sql": r.get("sql")} for r in step_results]
                        await _record_turn(conversations, ctx, req, synthesis, "result")
                        yield ev({"type": "start", "conversation_id": req.conversation_id,
                                  "columns": first.get("columns") or [], "row_count": len(step_results)})
                        yield ev({"type": "progress", "stage": "explaining", "message": "Generating answer…"})
                        yield ev({"type": "steps", "steps": steps_meta})
                        yield ev({"type": "token", "content": synthesis})
                        yield ev({"type": "rows", "rows": first.get("rows") or [],
                                  "columns": first.get("columns") or [], "row_count": first.get("row_count") or 0,
                                  "truncated": False})
                        if stream_redactions:
                            await _audit_output_redactions(c, ctx, conn, stream_redactions)
                            yield ev({"type": "redactions", "categories": stream_redactions})
                        if _verifier_enabled() and c.has(Verifier):
                            yield ev({"type": "verification", "ok": True,
                                      "note": "multi-step analysis; per-step results attached"})
                        yield ev({"type": "progress", "stage": "done", "message": "Complete"})
                        yield ev({"type": "done"})
                        return

                plan_result = await planner.plan(req.question, ctx, conn, provider,
                                                 extra_prompt=await _prompt_content(req),
                                                 history=await _conversation_history(conversations, ctx, req.conversation_id))
                if plan_result.clarification:
                    await _record_turn(conversations, ctx, req, plan_result.clarification, "clarification")
                    yield ev({"type": "progress", "stage": "clarifying", "message": "Requesting clarification"})
                    yield ev({"type": "clarification", "text": plan_result.clarification})
                    return

                yield ev({"type": "progress", "stage": "executing", "message": "Executing validated query…"})
                result = await engine.execute(ctx, plan_result.plan, conn)
            except DatahekError as e:
                yield ev({"type": "error", "code": e.code.value, "message": str(e)})
                return
            except Exception as e:
                yield ev({"type": "error", "message": str(e)})
                return

            columns = [c["name"] for c in result.columns]
            rows = [dict(zip(columns, [_json_safe(v) for v in row])) for row in result.rows]

            await _save_checkpoint(c, ctx, req, result.plan or plan_result.plan, result)
            yield ev({"type": "start", "conversation_id": req.conversation_id, "columns": columns, "row_count": result.row_count})
            yield ev({"type": "progress", "stage": "explaining", "message": "Generating answer…"})
            stream_redactions: set[str] = set()
            async for chunk in reasoner.stream_explanation(req.question, result, plan_result.plan, ctx):
                clean, found = sanitize_output(chunk)
                stream_redactions.update(found)
                yield ev({"type": "token", "content": clean})
            yield ev({"type": "rows", "rows": rows, "columns": columns, "row_count": result.row_count, "truncated": result.truncated})
            if stream_redactions:
                await _audit_output_redactions(c, ctx, conn, sorted(stream_redactions))
                yield ev({"type": "redactions", "categories": sorted(stream_redactions)})
            if _verifier_enabled() and c.has(Verifier):
                verdict = await c.resolve(Verifier).verify(req.question, result, ctx)
                yield ev({"type": "verification", "ok": verdict["ok"], "note": verdict["note"]})
            if _suggestions_enabled() and c.has(FollowUpSuggester):
                found = await c.resolve(FollowUpSuggester).suggest(req.question, result, ctx)
                if found:
                    yield ev({"type": "suggestions", "items": found})
            yield ev({"type": "progress", "stage": "done", "message": "Complete"})
            yield ev({"type": "done"})

        await _record_turn(conversations, ctx, req, None, "result")
        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"X-Conversation-ID": req.conversation_id or ""},
        )

    @app.post("/conversations", status_code=201)
    async def create_conversation(req: ConversationRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore
        from datahek.kernel.ids import entity_id

        conversations: ConversationStore = c.resolve(ConversationStore)
        ctx = RequestContext(source="api")
        conv_id = entity_id("conversation")
        await conversations.create(ctx, conv_id, title=req.title)
        return {"id": conv_id, "title": req.title}

    @app.get("/conversations")
    async def list_conversations(cursor: str | None = None, limit: int = 50,
                                 _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore

        conversations: ConversationStore = c.resolve(ConversationStore)
        ctx = RequestContext(source="api")
        return await conversations.list_by_project(ctx, ctx.project_id, cursor=cursor,
                                                   limit=min(limit, 200))

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore

        conversations: ConversationStore = c.resolve(ConversationStore)
        ctx = RequestContext(source="api")
        conv = await conversations.get(ctx, conversation_id)
        if conv is None:
            raise DatahekError(
                ErrorCode.CONVERSATION_NOT_FOUND,
                f"Conversation '{conversation_id}' not found",
                details={"conversation_id": conversation_id},
            )
        return conv

    @app.post("/prompts", status_code=201)
    async def create_prompt(req: PromptRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.prompts import PromptStore
        from datahek.kernel.ids import entity_id

        prompts: PromptStore = c.resolve(PromptStore)
        ctx = RequestContext(source="api")
        current = len(await prompts.list(ctx))
        limit = entitlements.limit("prompt.templates")
        if limit is not None and current >= limit:
            raise DatahekError(
                ErrorCode.RATE_LIMITED,
                f"Prompt template limit reached ({limit})",
                details={"resource": "prompt.templates", "limit": limit, "current": current},
            )
        pid = entity_id("prompt")
        await prompts.create(ctx, pid, name=req.name, content=req.content)
        await _audit_event(c, "prompt.create", "create", actor=_actor(_identity),
                           resource_ref=pid, payload={"name": req.name})
        return {"id": pid, "name": req.name, "content": req.content}

    @app.get("/prompts")
    async def list_prompts(_identity=Depends(_require_auth)):
        from datahek.contracts.prompts import PromptStore

        prompts: PromptStore = c.resolve(PromptStore)
        return await prompts.list(RequestContext(source="api"))

    @app.get("/prompts/{prompt_id}")
    async def get_prompt(prompt_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.prompts import PromptStore

        prompts: PromptStore = c.resolve(PromptStore)
        tpl = await prompts.get(RequestContext(source="api"), prompt_id)
        if tpl is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Prompt '{prompt_id}' not found")
        return tpl

    @app.delete("/prompts/{prompt_id}", status_code=204)
    async def delete_prompt(prompt_id: str, _identity=Depends(_require_auth)):
        from datahek.contracts.prompts import PromptStore

        prompts: PromptStore = c.resolve(PromptStore)
        ctx = RequestContext(source="api")
        if await prompts.get(ctx, prompt_id) is None:
            raise DatahekError(ErrorCode.NOT_FOUND, f"Prompt '{prompt_id}' not found")
        await prompts.delete(ctx, prompt_id)
        await _audit_event(c, "prompt.delete", "delete", actor=_actor(_identity),
                           resource_ref=prompt_id)

    @app.get("/evaluations")
    async def evaluations(_identity=Depends(_require_auth)):
        from datahek.contracts.evaluation import EvaluationStore

        store: EvaluationStore = c.resolve(EvaluationStore)
        ctx = RequestContext(source="api")
        runs = await store.list(ctx)
        aggregate = await store.aggregate(ctx)
        return {"total": aggregate["total"], "pass_rate": aggregate["pass_rate"], "runs": runs}

    @app.post("/evaluations/run")
    async def run_evaluations(_identity=Depends(_require_auth)):
        from datahek.contracts.evaluation import EvaluationStore
        from datahek.defaults.datasets import DatasetRunner
        from datahek.contracts.connections import Connection

        store: EvaluationStore = c.resolve(EvaluationStore)
        runner = DatasetRunner(store=store)
        ctx = RequestContext(source="api")
        conn = Connection(id="dataset", name="dataset", provider="dataset",
                          org_id=ctx.organization_id, project_id=ctx.project_id)
        return await runner.run(ctx, conn)

    return app