"""DataHek OSS API — health, connections, ask, conversations, evaluations, web UI."""
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datahek import __version__
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.reasoner import Reasoner
from datahek.contracts.verifier import Verifier
from datahek.defaults.guardrails import sanitize_output
from datahek.contracts.models import ModelProvider
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
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


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    actor: str = Field("anonymous", max_length=128)


class PromptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=4_000)


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

    async def _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner, entitlements):
        from datahek.contracts.misc import ConversationStore
        from datahek.contracts.prompts import PromptStore

        ctx = RequestContext(source="api", user_id=req.user_id, approval_id=req.approval_id,
                                 question=req.question)
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

        plan_result = await planner.plan(req.question, ctx, conn, provider, extra_prompt=extra_prompt)
        if plan_result.clarification:
            await _record_turn(conversations, ctx, req, plan_result.clarification, "clarification")
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
        await _save_checkpoint(c, ctx, req, plan_result.plan, result)
        explanation, redactions = sanitize_output(await reasoner.explain(req.question, result, plan_result.plan, ctx))
        if redactions:
            await _audit_output_redactions(c, ctx, conn, redactions)
        await _record_turn(conversations, ctx, req, explanation, "result")
        verification = None
        if _verifier_enabled() and c.has(Verifier):
            verification = await c.resolve(Verifier).verify(req.question, result, ctx)
        return {
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
        yield

    app = FastAPI(title="DataHek OSS", version=__version__, lifespan=lifespan)
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
            raise DatahekError(ErrorCode.UNAUTHORIZED, "API key required")
        ident = await auth_provider.authenticate_api_key(token)
        if not ident.authenticated:
            raise DatahekError(ErrorCode.UNAUTHORIZED, "Invalid API key")
        return ident

    @app.exception_handler(DatahekError)
    async def _datahek_error_handler(request: Request, exc: DatahekError) -> JSONResponse:
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

    @app.post("/auth/login")
    async def auth_login(req: LoginRequest, _identity=None):
        """Local login: returns the API token for subsequent requests (X-API-Key)."""
        ident = await auth_provider.authenticate(req.username, req.password)
        if not ident.authenticated:
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
    async def create_connection(req: ConnectionRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.connections import Connection
        from datahek.kernel.ids import entity_id

        if req.provider not in registry.ids():
            raise DatahekError(
                ErrorCode.UNSUPPORTED_PROVIDER,
                f"Provider '{req.provider}' is not supported",
                details={"provider": req.provider},
            )
        ctx = RequestContext(source="api")
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
        return {
            "id": conn.id, "name": conn.name, "provider": conn.provider,
            "host": conn.host, "port": conn.port, "database": conn.database,
        }

    @app.get("/connections")
    async def list_connections(_identity=Depends(_require_auth)):
        ctx = RequestContext(source="api")
        conns = await conn_mgr.list_connections(ctx)
        return [{
            "id": c.id, "name": c.name, "provider": c.provider,
            "host": c.host, "port": c.port, "database": c.database,
        } for c in conns]

    @app.post("/connections/test")
    async def test_connection(req: ConnectionRequest, _identity=Depends(_require_auth)):
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

    @app.delete("/connections/{connection_id}", status_code=204)
    async def delete_connection(connection_id: str, _identity=Depends(_require_auth)):
        ctx = RequestContext(source="api")
        await conn_mgr.remove(ctx, connection_id)

    @app.get("/approvals")
    async def list_approvals(_identity=Depends(_require_auth)):
        from datahek.contracts.misc import ApprovalService

        if not c.has(ApprovalService):
            return []
        service = c.resolve(ApprovalService)
        lister = getattr(service, "list_all", None)
        return lister() if lister is not None else []

    @app.post("/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: str, req: ApprovalDecisionRequest,
                              _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ApprovalService

        service = c.resolve(ApprovalService)
        mapped = "approved" if req.decision == "approve" else "rejected"
        await service.decide(approval_id, mapped, req.actor)
        return {"approval_id": approval_id, "status": await service.status(approval_id)}

    @app.get("/checkpoints")
    async def list_checkpoints(limit: int = 20, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import CheckpointStore

        store = c.resolve(CheckpointStore)
        items = await store.list(RequestContext(source="api"), limit=min(limit, 100))
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
        answer = await _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner, entitlements)
        return answer

    @app.post("/ask/stream")
    async def ask_stream(req: AskRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore
        from fastapi.responses import StreamingResponse
        import json as _json

        ctx = RequestContext(source="api", user_id=req.user_id, approval_id=req.approval_id,
                                 question=req.question)
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
                plan_result = await planner.plan(req.question, ctx, conn, provider,
                                                 extra_prompt=await _prompt_content(req))
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

            await _save_checkpoint(c, ctx, req, plan_result.plan, result)
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