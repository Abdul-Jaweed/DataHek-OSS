"""DataHek OSS MCP server — the same guarded pipeline over FastMCP.

Tools:
  data.list_tables(connection)     — tables in the connection's database
  data.table_schema(connection, table) — columns of a table
  data.ask(question, connection)   — full pipeline: plan → guardrails → execute → explain

Every tool runs the identical RequestContext(source="mcp") pipeline as the
API/CLI — MCP is never a privileged bypass (05-security-model).

Usage:
  python -m datahek.mcp_server                          # HTTP on :8001
  python -m datahek.mcp_server --transport stdio        # stdio
"""
import argparse
import logging

from fastmcp import FastMCP

from datahek.contracts.connections import ConnectionManager
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.engine.reasoner import Reasoner
from datahek.engine.schema import SchemaService
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError

logger = logging.getLogger(__name__)

SERVER_NAME = "data-vault"


def build_mcp_server(container=None) -> FastMCP:
    from datahek.defaults.container import build_app_container

    c = container or build_app_container()
    conn_mgr: ConnectionManager = c.resolve(ConnectionManager)
    registry: ProviderRegistry = c.resolve(ProviderRegistry)
    schema_service: SchemaService = c.resolve(SchemaService)
    planner: Planner = c.resolve(Planner)
    engine: Engine = c.resolve(Engine)
    reasoner: Reasoner = c.resolve(Reasoner)

    async def _connection(name_or_id: str):
        ctx = RequestContext(source="mcp")
        conns = await conn_mgr.list_connections(ctx)
        for conn in conns:
            if conn.name == name_or_id or conn.id == name_or_id:
                return ctx, conn
        raise DatahekError(
            ErrorCode.CONNECTION_NOT_FOUND,
            f"Connection '{name_or_id}' not found",
        )

    async def _safe(coro):
        try:
            return await coro
        except DatahekError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("MCP tool failed")
            return "Error: internal error"

    mcp = FastMCP(
        SERVER_NAME,
        instructions="DataHek OSS data tools — read-only, natural-language data access.",
    )

    @mcp.tool(name="data.list_tables")
    async def data_list_tables(connection: str) -> str:
        """List tables in the connection's database, with row counts."""
        async def run():
            ctx, conn = await _connection(connection)
            provider = registry.get(conn.provider)
            catalog = await schema_service.get_catalog(ctx, conn, provider)
            if not catalog.tables:
                return "No tables found"
            return "\n".join(f"{t.name} ({t.row_count or '?'} rows)" for t in catalog.tables)
        return await _safe(run())

    @mcp.tool(name="data.table_schema")
    async def data_table_schema(connection: str, table: str) -> str:
        """Show the columns of a table in the connection's database."""
        async def run():
            ctx, conn = await _connection(connection)
            provider = registry.get(conn.provider)
            catalog = await schema_service.get_catalog(ctx, conn, provider)
            for t in catalog.tables:
                if t.name == table:
                    if not t.columns:
                        return f"{table}: (no columns)"
                    return "\n".join(f"{col.name} {col.data_type}" for col in t.columns)
            return f"Table '{table}' not found"
        return await _safe(run())

    @mcp.tool(name="data.ask")
    async def data_ask(question: str, connection: str) -> str:
        """Ask a natural-language question; returns an explanation and result rows. Read-only."""
        async def run():
            ctx, conn = await _connection(connection)
            provider = registry.get(conn.provider)
            plan_result = await planner.plan(question, ctx, conn, provider)
            if plan_result.clarification:
                return f"Clarification: {plan_result.clarification}"
            result = await engine.execute(ctx, plan_result.plan, conn)
            explanation = await reasoner.explain(question, result, plan_result.plan, ctx)
            columns = [c["name"] for c in result.columns]
            lines = [explanation]
            for row in result.rows:
                lines.append("  " + ", ".join(f"{c}={v}" for c, v in zip(columns, row)))
            return "\n".join(lines)
        return await _safe(run())

    return mcp


def main():
    parser = argparse.ArgumentParser(description="DataHek OSS MCP server")
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="http")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    server = build_mcp_server()
    kwargs = {"host": args.host, "port": args.port} if args.transport != "stdio" else {}
    server.run(transport=args.transport, **kwargs)


if __name__ == "__main__":
    main()