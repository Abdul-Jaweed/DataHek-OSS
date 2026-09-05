"""Default masking policy — sensitive columns via schema semantic tags."""
from datahek.engine.plan import LogicalPlan
from datahek.engine.schema import SchemaCatalog
from datahek.kernel.context import RequestContext


class TagBasedMaskingPolicy:
    """Columns tagged 'sensitive', 'pii', or 'secret' in the schema catalog
    are masked for the plan's sources. Enterprise replaces via contract."""

    SENSITIVE_TAGS = frozenset({"sensitive", "pii", "secret"})

    async def sensitive_columns(self, ctx: RequestContext, plan: LogicalPlan, catalog: SchemaCatalog) -> set[str]:
        sources = {n.source for n in plan.nodes if hasattr(n, "source")}
        out: set[str] = set()
        for table in catalog.tables:
            if table.name not in sources:
                continue
            for col in table.columns:
                if self.SENSITIVE_TAGS & col.semantic_tags:
                    out.add(col.name)
        return out