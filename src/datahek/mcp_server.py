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
import os

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


async def run_guarded(coro, timeout_s: float = 120.0):
    """Run a tool coroutine with a hard timeout and contained errors.

    Prototype-inspired MCP boundary: hang-proof, secret-free error messages.
    """
    import asyncio

    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        return f"Error: tool timed out after {timeout_s:.0f}s"
    except DatahekError as e:
        return f"Error: {e}"
    except Exception:
        logger.exception("MCP tool failed")
        return "Error: internal error"


def build_mcp_auth():
    """Per-client MCP tokens — enabled only when DATAHEK_MCP_TOKENS is set.

    Format: token1,token2:scopeA|scopeB (scopes optional). Requests without a
    valid bearer token are rejected by FastMCP before any tool runs.
    """
    raw = os.environ.get("DATAHEK_MCP_TOKENS", "").strip()
    if not raw:
        return None
    tokens: dict[str, dict] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, _, scope_str = entry.partition(":")
        tokens[key] = {
            "client_id": f"mcp-{key[:6]}",
            "scopes": [sc for sc in scope_str.split("|") if sc],
        }
    required = [sc for sc in os.environ.get("DATAHEK_MCP_REQUIRED_SCOPES", "").split(",") if sc.strip()]
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(tokens=tokens, required_scopes=required or None)


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
        timeout = float(os.environ.get("DATAHEK_MCP_TOOL_TIMEOUT", "120"))
        return await run_guarded(coro, timeout_s=timeout)

    mcp = FastMCP(
        SERVER_NAME,
        instructions="DataHek OSS data tools — read-only, natural-language data access.",
        auth=build_mcp_auth(),
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

    @mcp.tool(name="data.list_connections")
    async def data_list_connections() -> str:
        """List available connections (name, provider, database — never credentials)."""
        async def run():
            ctx = RequestContext(source="mcp")
            conns = await conn_mgr.list_connections(ctx)
            if not conns:
                return "No connections configured"
            return "\n".join(f"{c.name} | {c.provider} | {c.database or '-'}" for c in conns)
        return await _safe(run())

    @mcp.tool(name="data.list_metrics")
    async def data_list_metrics() -> str:
        """List the semantic layer: named metric definitions the planner prefers."""
        async def run():
            from datahek.contracts.semantics import SemanticStore

            ctx = RequestContext(source="mcp")
            metrics = await c.resolve(SemanticStore).list(ctx)
            if not metrics:
                return "No metrics defined"
            return "\n".join(
                f"{m['name']} = {m['aggregate']}({m['column']}) on {m['table']}"
                + (f" where {m['filter']}" if m.get("filter") else "")
                for m in metrics)
        return await _safe(run())

    @mcp.tool(name="data.run_saved_query")
    async def data_run_saved_query(name_or_id: str) -> str:
        """Run a saved query by name/id. Reuses the newest matching checkpoint's
        stored plan when available (deterministic, no model call); otherwise
        executes through the full guarded pipeline."""
        async def run():
            from datahek.contracts.misc import CheckpointStore
            from datahek.contracts.saved import SavedQueryStore
            from datahek.engine.plan import LogicalPlan

            ctx = RequestContext(source="mcp")
            saved = await c.resolve(SavedQueryStore).get(ctx, name_or_id)
            if saved is None:
                found = [q for q in await c.resolve(SavedQueryStore).list_queries(ctx)
                         if q["name"] == name_or_id]
                saved = found[0] if found else None
            if saved is None:
                return f"Saved query '{name_or_id}' not found"

            if c.has(CheckpointStore):
                checkpoints = await c.resolve(CheckpointStore).list(ctx, limit=50)
                match = next((cp for cp in checkpoints
                              if cp["question"] == saved["question"]
                              and cp.get("plan") and cp.get("sql")), None)
                if match is not None:
                    plan = LogicalPlan.from_dict(match["plan"])
                    if plan.read_only:
                        conn = await conn_mgr.get_connection(ctx, match["connection_id"])
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
                        cols = [cc["name"] for cc in raw["columns"]]
                        lines = [f"[deterministic replay of checkpoint {match['id'][-8:]} · {match['sql']}]"]
                        for row in raw["rows"]:
                            lines.append("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, row)))
                        return "\n".join(lines)

            conn = await conn_mgr.get_connection(ctx, saved["connection_id"])
            provider = registry.get(conn.provider)
            plan_result = await planner.plan(saved["question"], ctx, conn, provider)
            if plan_result.clarification:
                return f"Clarification: {plan_result.clarification}"
            result = await engine.execute(ctx, plan_result.plan, conn)
            explanation = await reasoner.explain(saved["question"], result, plan_result.plan, ctx)
            cols = [cc["name"] for cc in result.columns]
            lines = [explanation]
            for row in result.rows:
                lines.append("  " + ", ".join(f"{cc}={v}" for cc, v in zip(cols, row)))
            return "\n".join(lines)
        return await _safe(run())

    @mcp.tool(name="data.replay_checkpoint")
    async def data_replay_checkpoint(checkpoint_id: str) -> str:
        """Deterministically re-run a stored plan — same SQL, no model involved."""
        async def run():
            from datahek.contracts.misc import CheckpointStore
            from datahek.engine.plan import LogicalPlan

            ctx = RequestContext(source="mcp")
            item = await c.resolve(CheckpointStore).get(ctx, checkpoint_id)
            if item is None:
                return f"Checkpoint '{checkpoint_id}' not found"
            plan = LogicalPlan.from_dict(item["plan"])
            if not plan.read_only:
                return "Replay blocked: stored plan is not read-only"
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
            cols = [cc["name"] for cc in raw["columns"]]
            lines = [f"[replay · {item['sql']}]"]
            for row in raw["rows"]:
                lines.append("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, row)))
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