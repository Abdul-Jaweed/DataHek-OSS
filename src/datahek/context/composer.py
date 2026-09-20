"""BudgetContextComposer — merge retrieved context under a token budget (FR-013).

Ordered degradation: profiles, taxonomy, topology, ontology, metrics are dropped
in that order when over budget (empty sections are simply absent, not
"dropped"). Schema, governance, and granularity are mandatory — if they cannot
fit, the composed context is marked insufficient and the compiler fails closed.
"""
from datahek.contracts.context import ComposedContext, RetrievedContext, RuntimeContext
from datahek.context.retriever import question_tokens

_OPTIONAL_ORDER = ("profiles", "taxonomy", "topology", "ontology", "metrics")


def estimate_tokens(value) -> int:
    if not value:
        return 0
    return max(0, len(str(value)) // 4)


def _metric_overlap(metric: dict, tokens: frozenset[str]) -> int:
    text = f"{metric.get('name', '')} {metric.get('description', '')}"
    return sum(1 for part in question_tokens(text) if part in tokens)


class BudgetContextComposer:
    async def compose(self, ctx, retrieved: RetrievedContext, runtime: RuntimeContext, *,
                      budget_tokens: int = 4000) -> ComposedContext:
        sections = {
            "schema": retrieved.schema,
            "governance": retrieved.governance,
            "granularity": retrieved.granularity,
            "profiles": retrieved.profiles,
            "taxonomy": retrieved.taxonomy,
            "topology": retrieved.topology,
            "ontology": retrieved.ontology,
            "metrics": retrieved.metrics,
        }
        dropped: list[str] = []
        tokens = (estimate_tokens(sections["schema"])
                  + estimate_tokens(sections["governance"])
                  + estimate_tokens(sections["granularity"]))
        insufficient = ""
        if tokens > budget_tokens:
            insufficient = "budget"
        else:
            for name in _OPTIONAL_ORDER:
                value = sections[name]
                if not value:
                    continue
                cost = estimate_tokens(value)
                if tokens + cost <= budget_tokens:
                    tokens += cost
                    continue
                if name == "metrics":
                    relevant = tuple(
                        metric for metric in value
                        if _metric_overlap(metric, question_tokens(runtime.question)) > 0)
                    relevant_cost = estimate_tokens(relevant)
                    if relevant and tokens + relevant_cost <= budget_tokens:
                        sections["metrics"] = relevant
                        tokens += relevant_cost
                        continue
                sections[name] = {} if name == "profiles" else (
                    () if name == "metrics" else None)
                dropped.append(name)

        return ComposedContext(
            context_id=retrieved.context_id, version=retrieved.version,
            schema_hash=retrieved.schema_hash, scope=retrieved.scope,
            connection_id=retrieved.connection_id, purpose=runtime.purpose,
            schema=sections["schema"],
            profiles=sections["profiles"] or {},
            topology=sections["topology"],
            granularity=sections["granularity"],
            taxonomy=sections["taxonomy"],
            ontology=sections["ontology"],
            governance=sections["governance"],
            metrics=sections["metrics"] or (),
            dropped=tuple(dropped),
            tokens_estimate=tokens,
            insufficient_reason=insufficient,
        )
