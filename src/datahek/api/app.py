"""DataHek OSS API — health, connections, ask, conversations, evaluations, web UI."""
from typing import Any

from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datahek import __version__
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.reasoner import Reasoner
from datahek.contracts.models import ModelProvider
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.engine.schema import SchemaService
from datahek.kernel.capabilities import OSS_CAPABILITIES
from datahek.kernel.context import RequestContext
from datahek.kernel.entitlements import EntitlementProvider
from datahek.kernel.errors import DatahekError, ErrorCode

_STATUS_BY_CODE = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONNECTION_NOT_FOUND: 404,
    ErrorCode.CONVERSATION_NOT_FOUND: 404,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.QUERY_DENIED: 422,
    ErrorCode.PLAN_INVALID: 422,
    ErrorCode.VALIDATION: 422,
    ErrorCode.CONNECTION_EXISTS: 409,
    ErrorCode.UNSUPPORTED_PROVIDER: 400,
    ErrorCode.CONNECTION_FAILED: 502,
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


class ConversationRequest(BaseModel):
    title: str | None = Field(None, max_length=200)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10_000)
    connection_id: str = Field(..., min_length=1)
    user_id: str = "anonymous"
    conversation_id: str | None = None


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

    async def _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner, entitlements):
        from datahek.contracts.misc import ConversationStore
        from datahek.defaults.guardrails import redact_pii

        ctx = RequestContext(source="api", user_id=req.user_id)
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

        plan_result = await planner.plan(req.question, ctx, conn, provider)
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
        rows = [dict(zip(columns, row)) for row in result.rows]
        explanation = redact_pii(await reasoner.explain(req.question, result, plan_result.plan, ctx))
        await _record_turn(conversations, ctx, req, explanation, "result")
        return {
            "clarification": None,
            "answer": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "plan_sources": plan_result.sources_used,
            "conversation_id": req.conversation_id,
        }

    app = FastAPI(title="DataHek OSS", version=__version__)
    conn_mgr: ConnectionManager = c.resolve(ConnectionManager)
    registry: ProviderRegistry = c.resolve(ProviderRegistry)
    planner: Planner = c.resolve(Planner)
    engine: Engine = c.resolve(Engine)
    entitlements: EntitlementProvider = c.resolve(EntitlementProvider)
    reasoner = c.resolve(Reasoner)

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
            "capabilities": {
                name: OSS_CAPABILITIES.supports(name)
                for name in ("sso", "multi_tenancy", "advanced_rbac", "policy_engine",
                             "centralized_audit", "usage_analytics", "high_availability")
            },
            "entitlements": entitlements.all_limits(),
            "providers": registry.ids(),
        }

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

    @app.post("/ask")
    async def ask(req: AskRequest, _identity=Depends(_require_auth)):
        answer = await _ask_pipeline(req, c, conn_mgr, registry, planner, engine, reasoner, entitlements)
        return answer

    @app.post("/ask/stream")
    async def ask_stream(req: AskRequest, _identity=Depends(_require_auth)):
        from datahek.contracts.misc import ConversationStore
        from fastapi.responses import StreamingResponse
        import json as _json

        ctx = RequestContext(source="api", user_id=req.user_id)
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

        plan_result = await planner.plan(req.question, ctx, conn, provider)
        if plan_result.clarification:
            await _record_turn(conversations, ctx, req, plan_result.clarification, "clarification")
            return StreamingResponse(
                iter([f"data: {_json.dumps({'type': 'clarification', 'text': plan_result.clarification})}\n\n"]),
                media_type="text/event-stream",
                headers={"X-Conversation-ID": req.conversation_id or ""},
            )

        result = await engine.execute(ctx, plan_result.plan, conn)
        columns = [c["name"] for c in result.columns]
        rows = [dict(zip(columns, row)) for row in result.rows]

        async def gen():
            yield f"data: {_json.dumps({'type': 'start', 'conversation_id': req.conversation_id, 'columns': columns, 'row_count': result.row_count})}\n\n"
            async for chunk in reasoner.stream_explanation(req.question, result, plan_result.plan, ctx):
                yield f"data: {_json.dumps({'type': 'token', 'content': chunk})}\n\n"
            yield f"data: {_json.dumps({'type': 'rows', 'rows': rows, 'columns': columns, 'row_count': result.row_count, 'truncated': result.truncated})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

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

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    async def index():
        from datahek.api.web import index_html
        return index_html()

    return app