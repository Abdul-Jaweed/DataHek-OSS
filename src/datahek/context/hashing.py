"""Canonical schema hashing — SHA-256 over a normalized schema representation.

Comments and row estimates are excluded: comments are untrusted text and
estimates drift without structural meaning (ADR-010).
"""
import hashlib
import json
from collections.abc import Sequence

from datahek.contracts.context import TableSchema


def canonical_schema_form(tables: Sequence[TableSchema]) -> str:
    payload = []
    for table in sorted(tables, key=lambda t: t.name):
        columns = [
            {
                "name": column.name,
                "type": column.data_type.strip().lower(),
                "nullable": column.nullable,
                "ordinal": column.ordinal,
            }
            for column in sorted(table.columns, key=lambda c: c.ordinal)
        ]
        payload.append({
            "table": table.name,
            "columns": columns,
            "primary_key": sorted(table.primary_key),
            "foreign_keys": sorted([list(fk) for fk in table.foreign_keys]),
            "indexes": sorted(table.indexes),
        })
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def schema_hash(tables: Sequence[TableSchema]) -> str:
    return hashlib.sha256(canonical_schema_form(tables).encode("utf-8")).hexdigest()
