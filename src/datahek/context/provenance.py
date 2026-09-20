"""Provenance and trust authority — humans outrank LLMs, deterministic facts are structural."""
from collections.abc import Iterable

from datahek.contracts.context import ProvenanceSource, TrustLevel, ValidationStatus

TRUST_ORDER: dict[TrustLevel, int] = {
    TrustLevel.SYSTEM: 4,
    TrustLevel.VALIDATED: 3,
    TrustLevel.STRUCTURAL: 2,
    TrustLevel.PROPOSED: 1,
    TrustLevel.UNTRUSTED: 0,
}

_AUTHORITATIVE = frozenset({TrustLevel.SYSTEM, TrustLevel.VALIDATED, TrustLevel.STRUCTURAL})


def effective_trust(levels: Iterable[TrustLevel]) -> TrustLevel:
    collected = list(levels)
    if not collected:
        return TrustLevel.UNTRUSTED
    return min(collected, key=lambda level: TRUST_ORDER[level])


def is_authoritative(trust: TrustLevel) -> bool:
    return trust in _AUTHORITATIVE


def can_override(candidate: TrustLevel, existing: TrustLevel) -> bool:
    return TRUST_ORDER[candidate] > TRUST_ORDER[existing]


def trust_for(source: ProvenanceSource, validation: ValidationStatus) -> TrustLevel:
    if source is ProvenanceSource.SYSTEM:
        return TrustLevel.SYSTEM
    if source is ProvenanceSource.HUMAN_VALIDATED:
        return TrustLevel.VALIDATED
    if validation in (ValidationStatus.APPROVED, ValidationStatus.EDITED):
        return TrustLevel.VALIDATED
    if source is ProvenanceSource.DATABASE:
        return TrustLevel.STRUCTURAL
    if source is ProvenanceSource.INFERRED:
        return TrustLevel.UNTRUSTED
    return TrustLevel.PROPOSED
