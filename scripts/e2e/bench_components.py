"""Component-level benchmark — every stage measured individually against real InsForge.

Run: K:/DataHek/.venv/Scripts/python.exe bench_components.py
"""
import asyncio
import json
import os
import pathlib
import statistics
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = pathlib.Path(r"K:\DataHek\DataHek\DataHek-OSS")
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
os.environ.setdefault("DATAHEK_METADATA_URL",
                      "postgresql://datahek:datahek@127.0.0.1:5433/datahek")

from datahek.contracts.audit import AuditEvent, AuditSink
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.misc import CheckpointStore, ConversationStore
from datahek.contracts.models import ModelProvider
from datahek.contracts.context import ArtifactKind, ContextRegistry, ContextStore, RuntimeContext
from datahek.context.compiler import PackageContextCompiler
from datahek.context.composer import BudgetContextComposer
from datahek.context.graph.builder import SchemaGraphBuilder
from datahek.context.graph.memory import InMemoryGraphRepository
from datahek.context.jobs.build_context import ContextBuildJob
from datahek.context.profiler import SchemaProfiler
from datahek.context.registry import ContextRegistryService
from datahek.context.retriever import ContextRetrieverService
from datahek.defaults.container import build_app_container
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.engine.compile import compile_sql
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.guardrails import InputGuardrail
from datahek.engine.plan import LogicalPlan, ReadNode, Aggregate, validate_plan
from datahek.engine.planner import Planner, build_context_summary, build_schema_summary
from datahek.engine.schema import SchemaService
from datahek.kernel.context import RequestContext

CONN_ID = "conn_000001a0c3c99dfede7287f9578f44e693fed7c7"
API = "http://127.0.0.1:8000"
RESULTS = {}

loop = asyncio.new_event_loop()


def run(coro):
    return loop.run_until_complete(coro)


def bench(name, fn, n=20):
    times = []
    for _ in range(n):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    p50 = statistics.median(times)
    p95 = sorted(times)[max(0, int(len(times) * 0.95) - 1)]
    RESULTS[name] = {"p50_ms": round(p50, 2), "p95_ms": round(p95, 2), "n": n}
    print(f"{name:<48} p50 {p50:9.2f} ms   p95 {p95:9.2f} ms   n={n}", flush=True)


def http(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    c = build_app_container()
    ctx = RequestContext(source="bench")
    conn_mgr = c.resolve(ConnectionManager)
    registry = c.resolve(ProviderRegistry)
    schema_service = c.resolve(SchemaService)
    engine = c.resolve(Engine)
    model = c.resolve(ModelProvider)

    connection = run(conn_mgr.get_connection(ctx, CONN_ID))
    provider = registry.get(connection.provider)
    print(f"connection: {connection.name} ({connection.provider})\n")

    # ── stores ──
    bench("store: connection read (PG)", lambda: run(conn_mgr.get_connection(ctx, CONN_ID)), 30)
    context_registry = c.resolve(ContextRegistry)
    active = run(context_registry.active(ctx, connection_id=CONN_ID, scope="connection"))
    bench("store: context registry active (PG)",
          lambda: run(context_registry.active(ctx, connection_id=CONN_ID, scope="connection")), 30)
    context_store = c.resolve(ContextStore)
    bench("store: context artifact read+deserialize (PG)",
          lambda: run(context_store.get(ctx, active.context_id, ArtifactKind.SCHEMA)), 30)
    checkpoints = c.resolve(CheckpointStore)

    def save_checkpoint():
        run(checkpoints.save(ctx, {"connection_id": CONN_ID, "question": "bench",
                                   "sql": "SELECT 1", "columns": [], "rows": []}))
    bench("store: checkpoint save", save_checkpoint, 20)

    conversations = c.resolve(ConversationStore)

    def append_turn():
        conversation_id = f"bench-{time.perf_counter_ns()}"
        run(conversations.create(ctx, conversation_id))
        run(conversations.append_message(ctx, conversation_id,
                                         {"role": "user", "content": "bench"}))
    bench("store: conversation create+append", append_turn, 20)
    audit = c.resolve(AuditSink)
    bench("store: audit event write",
          lambda: run(audit.record(AuditEvent(event_type="bench", actor="bench",
                                              action="bench"))), 20)

    # ── provider / engine ──
    bench("provider: connect+close",
          lambda: run(provider.close(run(provider.connect(connection)))), 10)
    bench("provider: schema introspection (force)",
          lambda: run(schema_service.get_catalog(ctx, connection, provider, force_refresh=True)), 5)

    catalog = run(schema_service.get_catalog(ctx, connection, provider))
    tables = schema_service.tables(catalog)
    columns = schema_service.columns(catalog)
    types = schema_service.column_types(catalog)
    plan = LogicalPlan(nodes=[ReadNode(
        source="unified_events", columns=["service_name"], group_by=["service_name"],
        aggregates=[Aggregate(function="count", column="*", alias="n")], limit=100)])
    bench("engine: compile_sql (static)", lambda: compile_sql(plan), 200)
    bench("engine: validate_plan (static)",
          lambda: validate_plan(plan, tables, columns, dialect="postgres", column_types=types), 200)
    bench("engine: input guardrail", lambda: run(InputGuardrail().run(ctx, {"question": "x"})), 200)
    bench("engine: full execute (count query)",
          lambda: run(engine.execute(ctx, plan, connection)), 5)

    # ── context build stages ──
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "bench.db")
        tmp_registry = ContextRegistryService(SqliteContextRegistry(path), SqliteContextStore(path))
        job = ContextBuildJob(
            schema_service=SchemaService(), registry_service=tmp_registry,
            profiler=SchemaProfiler(engine),
            graph_builder=SchemaGraphBuilder(InMemoryGraphRepository()), domain="InsForge")
        started = time.perf_counter()
        build = run(job.run(ctx, connection, provider, enrichment=False))
        total = (time.perf_counter() - started) * 1000
        print(f"\ncontext build total: {total:.0f} ms  state={build.state}")
        for stage in build.stages:
            print(f"  {stage.name:<12} {stage.status:<9} {stage.duration_ms:>7} ms  {stage.detail[:44]}")
        RESULTS["context build (full job)"] = {"p50_ms": round(total, 2), "p95_ms": round(total, 2), "n": 1}
        for stage in build.stages:
            RESULTS[f"context build: {stage.name}"] = {"p50_ms": stage.duration_ms,
                                                       "p95_ms": stage.duration_ms, "n": 1}

    # ── context retrieval / composition / compilation ──
    from datahek.contracts.context import ContextRetriever

    retriever = c.resolve(ContextRetriever)
    bench("context: retrieve",
          lambda: run(retriever.retrieve(ctx, connection_id=CONN_ID,
                                         question="revenue by customer")), 50)
    retrieved = run(retriever.retrieve(ctx, connection_id=CONN_ID,
                                       question="revenue by customer"))
    composer = BudgetContextComposer()
    bench("context: compose",
          lambda: run(composer.compose(ctx, retrieved, RuntimeContext(question="revenue"))), 50)
    composed = run(composer.compose(ctx, retrieved, RuntimeContext(question="revenue")))
    compiler = PackageContextCompiler()
    bench("context: compile",
          lambda: run(compiler.compile(ctx, composed, quality=retrieved.quality,
                                       freshness=retrieved.freshness)), 50)
    package = run(compiler.compile(ctx, composed, quality=retrieved.quality,
                                   freshness=retrieved.freshness))
    bench("planner: build_context_summary (static)",
          lambda: build_context_summary(package), 200)
    bench("planner: build_schema_summary (static)",
          lambda: build_schema_summary(catalog), 200)
    from datahek.engine.planner import Planner as _P
    bench("planner: build request payload (static)",
          lambda: _P._build_request("q", "schema", None, "", None, "postgres", None, ""), 200)
    bench("planner: parse+normalize+validate (static)",
          lambda: _P._parse('{"nodes":[{"type":"ReadNode","source":"unified_events",'
                            '"columns":["service_name"],"group_by":["service_name"],'
                            '"aggregates":[{"function":"count","column":"*","alias":"n"}],'
                            '"limit":100}]}'), 200)

    # ── model (upstream) ──
    times = []
    for _ in range(3):
        started = time.perf_counter()
        run(model.complete({"messages": [{"role": "user", "content": "Reply with OK"}],
                            "max_tokens": 5}))
        times.append((time.perf_counter() - started) * 1000)
    RESULTS["model: single completion (upstream)"] = {"p50_ms": round(statistics.median(times), 2),
                                                      "p95_ms": round(max(times), 2), "n": 3}
    print(f"\nmodel: single completion (upstream)  p50 {statistics.median(times):9.0f} ms  "
          f"n=3", flush=True)

    # ── HTTP surface ──
    bench("http: GET /health", lambda: http("GET", "/health"), 20)
    bench("http: POST /context/preview",
          lambda: http("POST", f"/connections/{CONN_ID}/context/preview",
                       {"question": "revenue by customer"}), 10)
    bench("http: GET /context/status",
          lambda: http("GET", f"/connections/{CONN_ID}/context"), 20)

    (pathlib.Path(__file__).parent / "bench_results.json").write_text(
        json.dumps(RESULTS, indent=2), encoding="utf-8")
    print("\nwrote bench_results.json")


if __name__ == "__main__":
    main()
