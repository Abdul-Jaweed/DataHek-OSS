# %% [markdown]
# # DataHek OSS — 02 · The pipeline, step by step
#
# The engine is deliberately explicit: **schema → plan → validate → guardrails
# → execute → mask → explain**. This notebook walks each step with real
# objects, no API layer in the way.

# %%
import sys, os
for _c in (os.getcwd(), os.path.join(os.getcwd(), "notebooks"), os.path.join(os.path.dirname(os.getcwd()), "notebooks")):
    if os.path.exists(os.path.join(_c, "datahek_demo.py")):
        sys.path.insert(0, _c)
        break
import tempfile
os.environ.setdefault("DATAHEK_DB_PATH", os.path.join(tempfile.gettempdir(), "datahek_notebooks.db"))

import asyncio
from datahek_demo import build_demo_db, make_container

db = build_demo_db()
container = make_container(db)
print("container ready")

# %% [markdown]
# ## 1 · Schema discovery
# The provider introspects the database and returns a catalog.

# %%
from datahek.contracts.connections import ConnectionManager
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import SchemaService
from datahek.kernel.context import RequestContext

ctx = RequestContext(source="notebook")
conn = (await container.resolve(ConnectionManager).list_connections(ctx))[0]
provider = container.resolve(ProviderRegistry).get(conn.provider)
catalog = await container.resolve(SchemaService).get_catalog(ctx, conn, provider)
print("tables:")
for t in catalog.tables:
    print(" -", t.name, "->", [c.name for c in t.columns])

# %% [markdown]
# ## 2 · Plan
# The planner (an LLM in production, a stub here) proposes a **LogicalPlan**.

# %%
from datahek.engine.planner import Planner

plan_result = await container.resolve(Planner).plan(
    "What is the average duration per service?", ctx, conn, provider)
plan = plan_result.plan
print("sources:", plan_result.sources_used)
print("plan:", plan.to_dict()["nodes"][0])

# %% [markdown]
# ## 3 · Validate
# Deterministic checks: tables, columns, dialect functions, read-only shape.

# %%
from datahek.engine.plan import validate_plan

tables = container.resolve(SchemaService).tables(catalog)
columns = container.resolve(SchemaService).columns(catalog)
validate_plan(plan, tables, columns, dialect=provider.capabilities.dialect)
print("plan is valid ✓")

# %% [markdown]
# ## 4 · Guardrails
# The pipeline returns a typed decision — ALLOW / DENY / REQUIRE_APPROVAL / RATE_LIMIT.

# %%
from datahek.engine.executor import Engine

engine = container.resolve(Engine)
result = await engine.execute(ctx, plan, conn)
print("executed:", result.row_count, "rows")

# %% [markdown]
# ## 5 · What was compiled
# Every execution compiles the plan to SQL — reproducible and auditable.

# %%
from datahek.engine.compile import compile_sql
print(compile_sql(plan))

# %% [markdown]
# ## 6 · Explain
# The reasoner formats the result for humans (an LLM in production).

# %%
from datahek.contracts.reasoner import Reasoner

explanation = await container.resolve(Reasoner).explain("avg per service", result, plan, ctx)
print(explanation)

# %% [markdown]
# **Takeaway:** the LLM only ever proposes; deterministic code decides and executes.
