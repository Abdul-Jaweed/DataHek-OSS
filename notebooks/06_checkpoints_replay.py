# %% [markdown]
# # DataHek OSS — 06 · Checkpoints & replay
#
# Every run is stored with its plan and compiled SQL. Replay re-executes a
# stored plan **deterministically — no LLM involved**.

# %%
import sys, os, tempfile
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break
os.environ["DATAHEK_DB_PATH"] = os.path.join(tempfile.gettempdir(), "datahek_nb06.db")

from datahek_demo import build_demo_db, make_client, show_rows

db = build_demo_db()
client, container = make_client(db)

# %% [markdown]
# ## Run two questions

# %%
for q in ["How many traces are there?", "What is the average duration per service?"]:
    client.post("/ask", json={"question": q, "connection_id": "conn_demo"})

for cp in client.get("/checkpoints").json():
    print(f"{cp['id'][-10:]}  rows={cp['row_count']:<3}  {cp['question']}")

# %% [markdown]
# ## Inspect a checkpoint's compiled SQL

# %%
cp_id = client.get("/checkpoints").json()[0]["id"]
detail = client.get(f"/checkpoints/{cp_id}").json()
print("question:", detail["question"])
print("sql:", detail["sql"])

# %% [markdown]
# ## Replay — same plan, same SQL, no model call

# %%
replay = client.post(f"/checkpoints/{cp_id}/replay").json()
print("replayed:", replay["replayed"])
print("sql:", replay["sql"])
show_rows(replay["rows"])

# %% [markdown]
# ## Audit trail
# Every guardrail decision and execution is recorded as JSONL alongside the app.

# %%
import json, glob
audit_files = sorted(glob.glob(os.path.join(tempfile.gettempdir(), "datahek_nb06.db*")) + glob.glob("datahek-audit.jsonl"))
print("audit files:", audit_files or "(audit path defaults to ./datahek-audit.jsonl)")
try:
    with open("datahek-audit.jsonl", encoding="utf-8") as f:
        events = [json.loads(line) for line in f][-3:]
    for e in events:
        print(e["event_type"], "|", e.get("decision"))
except FileNotFoundError:
    print("(run from the repo root to see the audit file)")

# %% [markdown]
# **Takeaway:** runs are reproducible artifacts — inspect, diff, and replay
# without re-planning or re-spending tokens.
