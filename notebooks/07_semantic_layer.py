# %% [markdown]
# # DataHek OSS — 07 · Semantic layer
#
# Define what words mean once: `error_count = count(*) where status = 'error'`.
# The planner receives these definitions and prefers them over guessing.

# %%
import sys, os, tempfile
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break
os.environ["DATAHEK_DB_PATH"] = os.path.join(tempfile.gettempdir(), "datahek_nb07.db")

from datahek_demo import build_demo_db, make_client

db = build_demo_db()
client, container = make_client(db)

# %% [markdown]
# ## Define a metric

# %%
r = client.post("/metrics", json={
    "name": "error_count",
    "table": "traces",
    "aggregate": "count",
    "column": "*",
    "filter": "status = 'error'",
    "description": "number of error traces, failures",
})
print("created:", r.status_code)
print(client.get("/metrics").json())

# %% [markdown]
# ## What the planner sees
# The semantic catalog is injected into the planner prompt (relevance-ordered).

# %%
from datahek.engine.planner import _format_metrics

print(_format_metrics(client.get("/metrics").json(), "what is the error count?"))

# %% [markdown]
# ## Ask using the business term

# %%
r = client.post("/ask", json={"question": "What is the error count?",
                              "connection_id": "conn_demo"})
print("answer:", r.json()["answer"])
print("rows:", r.json()["rows"])

# %% [markdown]
# ## Invalid definitions are refused
# Aggregates are validated against the supported function set.

# %%
r = client.post("/metrics", json={"name": "median_ms", "table": "traces", "aggregate": "median"})
print("status:", r.status_code, "|", r.json()["message"])

# %% [markdown]
# **Takeaway:** metrics turn tribal knowledge into a catalog — consistent
# across users, auditable, and validated.
