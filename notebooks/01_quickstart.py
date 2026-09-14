# %% [markdown]
# # DataHek OSS — 01 · Quick start
#
# End-to-end in one cell: create the demo database, wire an offline stub
# model, and ask a question through the *real* API pipeline
# (schema discovery → plan → validate → guardrails → execute → explain).
#
# Everything here runs without credentials or network access.

# %%
import sys, os
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break
import tempfile
os.environ.setdefault("DATAHEK_DB_PATH", os.path.join(tempfile.gettempdir(), "datahek_notebooks.db"))

from datahek_demo import build_demo_db, make_client, show_rows

db = build_demo_db()
print("demo database:", db)

# %%
client, container = make_client(db)

print("health:", client.get("/health").json()["status"])
print("connections:", [c["name"] for c in client.get("/connections").json()])

# %% [markdown]
# ## Ask a question

# %%
r = client.post("/ask", json={"question": "How many traces are there?", "connection_id": "conn_demo"})
print("answer:", r.json()["answer"])
show_rows(r.json()["rows"])

# %% [markdown]
# ## Ask for an aggregate

# %%
r = client.post("/ask", json={"question": "What is the average duration per service?", "connection_id": "conn_demo"})
show_rows(r.json()["rows"])

# %% [markdown]
# ## Stream it (SSE)
#
# The production UI consumes the same `progress → start → token → rows → done` events.

# %%
with client.stream("POST", "/ask/stream", json={
        "question": "How many errors per service?",
        "connection_id": "conn_demo"}) as resp:
    for line in resp.iter_lines():
        if line.startswith("data: "):
            print(line[6:][:110])

# %% [markdown]
# ## Inspect what persisted
#
# Conversations, checkpoints, and audit records land in SQLite next to the demo.

# %%
print("checkpoints:", [(c["question"], c["row_count"]) for c in client.get("/checkpoints").json()])
