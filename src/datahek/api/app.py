"""DataHek OSS API — health, connections, and the ask endpoint."""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datahek import __version__
from datahek.contracts.connections import ConnectionManager
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
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.QUERY_DENIED: 422,
    ErrorCode.PLAN_INVALID: 422,
    ErrorCode.VALIDATION: 422,
    ErrorCode.CONNECTION_EXISTS: 409,
    ErrorCode.UNSUPPORTED_PROVIDER: 400,
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


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10_000)
    connection_id: str = Field(..., min_length=1)
    user_id: str = "anonymous"


def create_app(container=None) -> FastAPI:
    """Build the FastAPI app. ``container`` injectable for tests/Enterprise."""
    from datahek.defaults.container import build_app_container

    c = container or build_app_container()
    app = FastAPI(title="DataHek OSS", version=__version__)
    conn_mgr: ConnectionManager = c.resolve(ConnectionManager)
    registry: ProviderRegistry = c.resolve(ProviderRegistry)
    planner: Planner = c.resolve(Planner)
    engine: Engine = c.resolve(Engine)
    entitlements: EntitlementProvider = c.resolve(EntitlementProvider)

    @app.exception_handler(DatahekError)
    async def _datahek_error_handler(request: Request, exc: DatahekError) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS_BY_CODE.get(exc.code, 400),
            content=exc.to_dict(),
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
    async def create_connection(req: ConnectionRequest):
        from datahek.contracts.connections import Connection
        from datahek.kernel.ids import entity_id

        if req.provider not in registry.ids():
            raise DatahekError(
                ErrorCode.UNSUPPORTED_PROVIDER,
                f"Provider '{req.provider}' is not supported",
                details={"provider": req.provider},
            )
        ctx = RequestContext(source="api")
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
    async def list_connections():
        ctx = RequestContext(source="api")
        conns = await conn_mgr.list_connections(ctx)
        return [{
            "id": c.id, "name": c.name, "provider": c.provider,
            "host": c.host, "port": c.port, "database": c.database,
        } for c in conns]

    @app.post("/ask")
    async def ask(req: AskRequest):
        ctx = RequestContext(source="api", user_id=req.user_id)
        conn = await conn_mgr.get_connection(ctx, req.connection_id)
        provider = registry.get(conn.provider)

        plan_result = await planner.plan(req.question, ctx, conn, provider)
        if plan_result.clarification:
            return {
                "clarification": plan_result.clarification,
                "rows": None, "columns": None, "row_count": 0,
                "truncated": False, "plan_sources": [],
            }

        result = await engine.execute(ctx, plan_result.plan, conn)
        columns = [c["name"] for c in result.columns]
        rows = [dict(zip(columns, row)) for row in result.rows]
        return {
            "clarification": None,
            "columns": columns,
            "rows": rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "plan_sources": plan_result.sources_used,
        }

    return app