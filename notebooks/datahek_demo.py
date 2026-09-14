"""Shared helpers for the DataHek OSS teaching notebooks.

Everything here is deterministic and offline: a stub model replaces the LLM
so the full pipeline (validation, guardrails, execution, masking, approvals)
runs without credentials or network access.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

DEMO_ROWS = [
    ("payment-api", "ok", 42, "2026-09-01 10:00:00"),
    ("payment-api", "error", 310, "2026-09-01 10:01:00"),
    ("auth-service", "ok", 150, "2026-09-01 10:02:00"),
    ("order-service", "ok", 95, "2026-09-01 10:03:00"),
    ("order-service", "error", 880, "2026-09-01 10:04:00"),
    ("auth-service", "error", 1200, "2026-09-01 10:05:00"),
    ("inventory", "ok", 60, "2026-09-01 10:06:00"),
    ("inventory", "ok", 55, "2026-09-01 10:07:00"),
]

META_ROWS = [
    ("auth-service", "gold", "platform"),
    ("order-service", "silver", "commerce"),
    ("payment-api", "gold", "payments"),
    ("inventory", "bronze", "ops"),
]


def build_demo_db(path: str | None = None) -> str:
    """Create the demo SQLite database (traces + service_meta). Returns the path."""
    path = path or os.path.join(tempfile.gettempdir(), "datahek_demo.db")
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE traces (service TEXT, status TEXT, duration_ms INTEGER, ts TEXT)")
    conn.executemany("INSERT INTO traces VALUES (?, ?, ?, ?)", DEMO_ROWS)
    conn.execute("CREATE TABLE service_meta (service TEXT, tier TEXT, owner TEXT)")
    conn.executemany("INSERT INTO service_meta VALUES (?, ?, ?)", META_ROWS)
    conn.commit()
    conn.close()
    return path


class StubModel:
    """Deterministic planner/explainer/verifier — no network, no API key."""

    def __init__(self, complex_question: bool = False):
        self._complex = complex_question

    async def complete(self, request):
        from datahek.contracts.models import ModelResponse

        system = request["messages"][0]["content"]
        user = request["messages"][1]["content"] if len(request["messages"]) > 1 else ""

        if "decompose" in system.lower():
            if self._complex:
                return ModelResponse(content='{"complex": true, "steps": '
                                             '["How many traces are there?", '
                                             '"What is the average duration per service?"]}')
            return ModelResponse(content='{"complex": false, "steps": []}')

        if "verifier" in system.lower():
            return ModelResponse(content='{"ok": true, "note": "stub verification passed"}')

        if "you are an analyst" in system.lower():
            return ModelResponse(content="Combined stub answer: 8 traces; auth-service is slowest.")

        if "explain" in system.lower():
            return ModelResponse(content="Stub explanation: the result is shown in the table below.")

        # The user message is "Question: <q>\n\nSchema:\n<summary>" (history may precede it).
        if "Question:" in user:
            question = user.split("Question:", 1)[-1].split("\n\n", 1)[0].strip().lower()
        else:
            question = user.lower()
        if "join" in question or "tier" in question:
            return ModelResponse(content="""{"nodes": [{"type": "ReadNode",
                "source": "traces", "columns": ["service_meta.tier"],
                "group_by": ["service_meta.tier"],
                "aggregates": [{"function": "avg", "column": "duration_ms", "alias": "avg_ms"}],
                "joins": [{"table": "service_meta", "join_type": "inner",
                           "on_left": "service", "on_right": "service"}],
                "limit": 10}]}""")
        if "error" in question:
            return ModelResponse(content="""{"nodes": [{"type": "ReadNode", "source": "traces",
                "columns": ["service"], "group_by": ["service"],
                "aggregates": [{"function": "count", "column": "*", "alias": "error_count"}],
                "filter": "status = 'error'", "order_by": ["error_count DESC"], "limit": 10}]}""")
        if "average" in question or "avg" in question:
            return ModelResponse(content="""{"nodes": [{"type": "ReadNode", "source": "traces",
                "columns": ["service"], "group_by": ["service"],
                "aggregates": [{"function": "avg", "column": "duration_ms", "alias": "avg_duration"}],
                "order_by": ["avg_duration DESC"], "limit": 10}]}""")
        return ModelResponse(content="""{"nodes": [{"type": "ReadNode", "source": "traces",
            "columns": ["service"],
            "aggregates": [{"function": "count", "column": "*", "alias": "total_traces"}],
            "limit": 10}]}""")

    async def stream(self, request):
        yield "Stub explanation."


def make_client(db_path: str, complex_question: bool = False, connection_name: str = "demo"):
    """Build an offline API client: demo SQLite connection + stub model."""
    from fastapi.testclient import TestClient

    from datahek.api.app import create_app
    from datahek.contracts.connections import Connection, ConnectionManager
    from datahek.contracts.models import ModelProvider
    from datahek.defaults.connections import LocalConnectionManager
    from datahek.defaults.container import build_app_container

    container = build_app_container()
    container.override(ModelProvider, StubModel(complex_question=complex_question))
    container.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_demo", name=connection_name, provider="sqlite",
                   org_id="default", project_id="default", host=db_path, database="demo"),
    ]))
    return TestClient(create_app(container)), container


def make_container(db_path: str):
    """Engine-level container for step-by-step pipeline notebooks."""
    from datahek.contracts.connections import Connection, ConnectionManager
    from datahek.contracts.models import ModelProvider
    from datahek.defaults.connections import LocalConnectionManager
    from datahek.defaults.container import build_app_container

    container = build_app_container()
    container.override(ModelProvider, StubModel())
    container.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_demo", name="demo", provider="sqlite",
                   org_id="default", project_id="default", host=db_path, database="demo"),
    ]))
    return container


def show_rows(rows, limit: int = 10):
    """Pretty-print a list of row dicts (notebook-friendly)."""
    if not rows:
        print("(no rows)")
        return
    for row in rows[:limit]:
        print(" | ".join(f"{k}={v}" for k, v in row.items()))
