"""DataHek CLI — ask questions, manage connections, interactive loop.

Usage:
    python -m datahek.cli connections
    python -m datahek.cli ask "question" --connection <name-or-id>
    python -m datahek.cli interactive
"""
import argparse
import asyncio
import sys

from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError


def build_cli_container():
    from datahek.defaults.container import build_app_container
    return build_app_container()


async def find_connection_by_name(conn_mgr: ConnectionManager, ctx: RequestContext, name_or_id: str) -> Connection:
    conns = await conn_mgr.list_connections(ctx)
    for c in conns:
        if c.name == name_or_id or c.id == name_or_id:
            return c
    raise DatahekError(
        ErrorCode.CONNECTION_NOT_FOUND,
        f"Connection '{name_or_id}' not found",
    )


async def ask_one(container, question: str, connection_name: str) -> dict:
    from datahek.contracts.reasoner import Reasoner

    conn_mgr: ConnectionManager = container.resolve(ConnectionManager)
    registry = container.resolve(ProviderRegistry)
    planner = container.resolve(Planner)
    engine = container.resolve(Engine)
    reasoner: Reasoner = container.resolve(Reasoner)

    ctx = RequestContext(source="cli")
    conn = await find_connection_by_name(conn_mgr, ctx, connection_name)
    provider = registry.get(conn.provider)

    plan_result = await planner.plan(question, ctx, conn, provider)
    if plan_result.clarification:
        print(f"[clarification] {plan_result.clarification}")
        return {"answer": plan_result.clarification, "rows": None}

    result = await engine.execute(ctx, plan_result.plan, conn)
    explanation = await reasoner.explain(question, result, plan_result.plan, ctx)
    print(explanation)
    columns = [c["name"] for c in result.columns]
    for row in result.rows:
        print("  " + ", ".join(f"{c}={v}" for c, v in zip(columns, row)))
    return {"answer": explanation, "rows": [dict(zip(columns, r)) for r in result.rows]}


async def _interactive(container):
    conn_mgr: ConnectionManager = container.resolve(ConnectionManager)
    ctx = RequestContext(source="cli")
    print("DataHek OSS — interactive. Type /help for commands, /exit to quit.")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            print("bye")
            return
        if line == "/help":
            print("  ask <connection> <question>  — run a query")
            print("  /connections                 — list connections")
            print("  /exit                        — quit")
            continue
        if line == "/connections":
            conns = await conn_mgr.list_connections(ctx)
            if not conns:
                print("  No connections")
            for c in conns:
                print(f"  {c.name} ({c.provider}) {c.host or ''}:{c.port or ''}")
            continue
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0] == "ask":
            try:
                await ask_one(container, parts[2], parts[1])
            except DatahekError as e:
                print(f"  error: {e}")
            continue
        print("  Usage: ask <connection> <question>")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("DataHek OSS CLI")
        print("Usage:")
        print("  datahek connections")
        print('  datahek ask "question" --connection <name-or-id>')
        print("  datahek interactive")
        return 0 if argv and argv[0] in ("-h", "--help") else 1

    command, rest = argv[0], argv[1:]
    if command == "connections":
        conns = asyncio.run(_list_connections())
        if not conns:
            print("No connections")
        for name, provider, host, port in conns:
            print(f"{name} ({provider}) {host or ''}:{port or ''}")
        return 0

    if command == "ask":
        parser = argparse.ArgumentParser(prog="datahek ask")
        parser.add_argument("question")
        parser.add_argument("--connection", required=True)
        args = parser.parse_args(rest)
        try:
            asyncio.run(ask_one(build_cli_container(), args.question, args.connection))
        except DatahekError as e:
            print(f"error: {e}")
            return 2
        return 0

    if command == "interactive":
        asyncio.run(_interactive(build_cli_container()))
        return 0

    print(f"Unknown command '{command}'")
    print("Usage: datahek connections | ask | interactive")
    return 1


async def _list_connections():
    conn_mgr: ConnectionManager = build_cli_container().resolve(ConnectionManager)
    conns = await conn_mgr.list_connections(RequestContext(source="cli"))
    return [(c.name, c.provider, c.host, c.port) for c in conns]


if __name__ == "__main__":
    raise SystemExit(main())