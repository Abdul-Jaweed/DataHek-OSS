# %% [markdown]
# # DataHek OSS — 08 · Evaluation
#
# Every execution is scored for validity, safety, and latency; the repo also
# ships a curated regression dataset with planned **and** refused cases.

# %%
import sys, os
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break

from datahek_demo import build_demo_db, make_client

db = build_demo_db()
client, container = make_client(db)

# %% [markdown]
# ## The built-in regression dataset
# Each case carries a reference plan; refused cases must raise.

# %%
from datahek.defaults.datasets import builtin_cases

for case in builtin_cases():
    print(f"- {case.name}: expect={case.expect}")

# %% [markdown]
# ## Run the dataset
# The runner executes each case through the real engine with an in-memory
# demo catalog — no database or LLM required.

# %%
import asyncio
from datahek.contracts.connections import Connection
from datahek.defaults.datasets import DatasetRunner
from datahek.kernel.context import RequestContext

runner = DatasetRunner()
conn = Connection(id="c1", name="dataset", provider="clickhouse", org_id="default", project_id="default")
report = await runner.run(RequestContext(source="notebook"), conn)

print("total:", report["total"])
print("passed:", report["passed"])
print("pass_rate:", report["pass_rate"])
for run in report["cases"][:5]:
    print(" -", {k: run.get(k) for k in ("name", "passed", "scores")})

# %% [markdown]
# ## Live execution scoring
# Real asks are scored by the evaluation hook as they run.

# %%
client.post("/ask", json={"question": "How many traces are there?", "connection_id": "conn_demo"})
summary = client.get("/evaluations").json()
print({k: v for k, v in summary.items() if k != "runs"})

# %% [markdown]
# **Takeaway:** changes ship with measured regressions, not vibes — and the
# dataset runs anywhere, offline.
