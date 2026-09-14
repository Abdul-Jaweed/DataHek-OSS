# %% [markdown]
# # DataHek OSS — 05 · Human-in-the-loop approvals
#
# Large exports, unbounded scans, and sensitive tables pause for an explicit
# human decision before executing.

# %%
import sys, os, tempfile
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break

# A low threshold makes the gate easy to see; production default is 1000.
os.environ["DATAHEK_APPROVAL_ROW_LIMIT"] = "5"
os.environ["DATAHEK_DB_PATH"] = os.path.join(tempfile.gettempdir(), "datahek_nb05.db")

from datahek_demo import build_demo_db, make_client

db = build_demo_db()
client, container = make_client(db)
print("threshold:", os.environ["DATAHEK_APPROVAL_ROW_LIMIT"])

# %% [markdown]
# ## The question hits the gate

# %%
r = client.post("/ask", json={"question": "Give me every trace record with no limit",
                              "connection_id": "conn_demo"})
print("status:", r.status_code)
print(r.json())
approval_id = r.json()["details"]["approval_id"]

# %% [markdown]
# ## The approval inbox

# %%
for a in client.get("/approvals").json():
    print(f"{a['status']:8s} {a['reason']}  ({a['id'][-8:]})")

# %% [markdown]
# ## Approve → the same question executes

# %%
d = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve", "actor": "admin"})
print("decision:", d.json())

r2 = client.post("/ask", json={"question": "Give me every trace record with no limit",
                               "connection_id": "conn_demo", "approval_id": approval_id})
print("status:", r2.status_code, "| rows:", len(r2.json()["rows"]))

# %% [markdown]
# ## Rejection blocks execution

# %%
r3 = client.post("/ask", json={"question": "export everything", "connection_id": "conn_demo"})
aid2 = r3.json()["details"]["approval_id"]
client.post(f"/approvals/{aid2}/decide", json={"decision": "reject", "actor": "admin"})
r4 = client.post("/ask", json={"question": "export everything", "connection_id": "conn_demo",
                               "approval_id": aid2})
print("status:", r4.status_code, "|", r4.json()["message"])

# %% [markdown]
# **Takeaway:** autonomy with accountability — the engine can *ask* for
# permission, and every decision is auditable.
