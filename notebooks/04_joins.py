# %% [markdown]
# # DataHek OSS — 04 · JOINs
#
# Multi-table questions compile to real SQL joins — with the same validation
# and policy coverage as single-table queries.

# %%
import sys, os
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break
import tempfile
os.environ.setdefault("DATAHEK_DB_PATH", os.path.join(tempfile.gettempdir(), "datahek_notebooks.db"))

import asyncio
from datahek_demo import build_demo_db, make_client, show_rows

db = build_demo_db()
client, container = make_client(db)

# %% [markdown]
# ## Ask a joined question
# "per tier" lives on `service_meta`; durations live on `traces` — the planner
# joins them on `service`.

# %%
r = client.post("/ask", json={
    "question": "What is the average duration per service tier?",
    "connection_id": "conn_demo"})
print("answer:", r.json()["answer"])
show_rows(r.json()["rows"])

# %% [markdown]
# ## The compiled SQL

# %%
cp = client.get("/checkpoints").json()[0]
print(cp["sql"])

# %% [markdown]
# ## Build the plan by hand
# A `Join` is part of the AST — inspect, validate, and compile it directly.

# %%
from datahek.engine.plan import Aggregate, Join, LogicalPlan, ReadNode
from datahek.engine.compile import compile_sql

plan = LogicalPlan(nodes=[ReadNode(
    source="traces",
    columns=["service_meta.tier"],
    group_by=["service_meta.tier"],
    aggregates=[Aggregate(function="avg", column="duration_ms", alias="avg_ms")],
    joins=[Join(table="service_meta", on_left="service", on_right="service")],
    limit=10,
)])
print(compile_sql(plan))

# %% [markdown]
# ## Join tables are policy-checked too
# A join to a sensitive table triggers approval even when the base table is fine.

# %%
from datahek.defaults.policy import LocalPolicyEngine
from datahek.kernel.context import RequestContext

policy = LocalPolicyEngine()
sensitive = LogicalPlan(nodes=[ReadNode(
    source="traces", columns=["salaries.amount"],
    joins=[Join(table="salaries", on_left="service", on_right="service")],
)])
decision = await policy.evaluate({"plan": sensitive, "tables": ["traces", "salaries"]})
print(decision["action"], "—", decision["reason"])

# %% [markdown]
# **Takeaway:** joins are first-class in the AST — validated, compiled
# per-dialect, and covered by every guardrail.
