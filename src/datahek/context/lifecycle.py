"""Context lifecycle — explicit state machine with legal transitions only."""
from datahek.contracts.context import LifecycleState
from datahek.kernel.errors import DatahekError, ErrorCode

LEGAL_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.DISCOVERED: frozenset({LifecycleState.PROFILING, LifecycleState.FAILED}),
    LifecycleState.PROFILING: frozenset({LifecycleState.ENRICHING, LifecycleState.FAILED}),
    LifecycleState.ENRICHING: frozenset({LifecycleState.GENERATED, LifecycleState.FAILED}),
    LifecycleState.GENERATED: frozenset({LifecycleState.PENDING_VALIDATION,
                                         LifecycleState.ACTIVE, LifecycleState.FAILED}),
    LifecycleState.PENDING_VALIDATION: frozenset({LifecycleState.VALIDATED,
                                                  LifecycleState.STALE,
                                                  LifecycleState.FAILED}),
    LifecycleState.VALIDATED: frozenset({LifecycleState.ACTIVE, LifecycleState.STALE}),
    LifecycleState.ACTIVE: frozenset({LifecycleState.STALE, LifecycleState.REBUILDING,
                                      LifecycleState.DEGRADED, LifecycleState.SUPERSEDED}),
    LifecycleState.DEGRADED: frozenset({LifecycleState.ACTIVE, LifecycleState.REBUILDING,
                                        LifecycleState.STALE, LifecycleState.FAILED}),
    LifecycleState.STALE: frozenset({LifecycleState.REBUILDING, LifecycleState.SUPERSEDED}),
    LifecycleState.REBUILDING: frozenset({LifecycleState.PROFILING, LifecycleState.ACTIVE,
                                          LifecycleState.DEGRADED, LifecycleState.FAILED}),
    LifecycleState.FAILED: frozenset({LifecycleState.REBUILDING, LifecycleState.SUPERSEDED}),
    LifecycleState.SUPERSEDED: frozenset(),
}

TERMINAL_STATES = frozenset({LifecycleState.SUPERSEDED})


def next_states(current: LifecycleState) -> frozenset[LifecycleState]:
    return LEGAL_TRANSITIONS.get(current, frozenset())


def is_transition_allowed(current: LifecycleState, nxt: LifecycleState) -> bool:
    return nxt in next_states(current)


def assert_transition(current: LifecycleState, nxt: LifecycleState) -> None:
    if is_transition_allowed(current, nxt):
        return
    raise DatahekError(
        ErrorCode.VALIDATION,
        f"Illegal context lifecycle transition: {current.value} -> {nxt.value}",
        details={"from": current.value, "to": nxt.value,
                 "allowed": sorted(s.value for s in next_states(current))},
    )
