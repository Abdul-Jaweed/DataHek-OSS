"""Result masking — sensitive columns masked before the reasoner sees them.

Per 07-agent-contracts: the model never reasons over unmasked sensitive
columns. Masking is a pure transformation on normalized results.
"""
from datahek.engine.executor import QueryResult


def mask_result(result: QueryResult, sensitive: set[str]) -> QueryResult:
    """Replace values of sensitive columns with '***'."""
    if not sensitive:
        return result
    indexes = [i for i, c in enumerate(result.columns) if c["name"] in sensitive]
    if not indexes:
        return result
    masked_rows = []
    for row in result.rows:
        vals = list(row)
        for i in indexes:
            vals[i] = "***"
        masked_rows.append(tuple(vals))
    return QueryResult(
        columns=result.columns,
        rows=masked_rows,
        row_count=result.row_count,
        truncated=result.truncated,
        execution=result.execution,
    )