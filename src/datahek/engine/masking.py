"""Result masking — sensitive columns masked before the reasoner sees them.

Per 07-agent-contracts: the model never reasons over unmasked sensitive
columns. Masking is a pure transformation on normalized results.

Strategies (DATAHEK_MASK_MODE):
  redact  — replace with *** (default)
  hash    — salted SHA-256 digest prefix (stable, joinable, non-reversible)
  partial — keep the last 4 characters (****1234)
"""
import hashlib
import os

from datahek.engine.executor import QueryResult


def mask_value(value, mode: str) -> str:
    """Apply the masking strategy to a single value."""
    if mode == "hash":
        salt = os.environ.get("DATAHEK_MASK_SALT", "datahek")
        digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
        return f"sha256:{digest[:12]}"
    if mode == "partial":
        text = str(value)
        return f"****{text[-4:]}" if len(text) > 4 else "****"
    return "***"


def mask_result(result: QueryResult, sensitive: set[str], mode: str | None = None) -> QueryResult:
    """Mask values of sensitive columns using the configured strategy."""
    if not sensitive:
        return result
    indexes = [i for i, c in enumerate(result.columns) if c["name"] in sensitive]
    if not indexes:
        return result
    mode = mode or os.environ.get("DATAHEK_MASK_MODE", "redact")
    if mode not in ("redact", "hash", "partial"):
        mode = "redact"
    masked_rows = []
    for row in result.rows:
        vals = list(row)
        for i in indexes:
            vals[i] = mask_value(vals[i], mode)
        masked_rows.append(tuple(vals))
    return QueryResult(
        columns=result.columns,
        rows=masked_rows,
        row_count=result.row_count,
        truncated=result.truncated,
        execution=result.execution,
    )
