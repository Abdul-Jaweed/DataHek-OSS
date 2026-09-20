"""Context lifecycle — legal transitions only (ADR-009, architecture diagram)."""
import unittest

from datahek.contracts.context import LifecycleState
from datahek.context.lifecycle import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    assert_transition,
    is_transition_allowed,
    next_states,
)
from datahek.kernel.errors import DatahekError, ErrorCode


class TestLifecycle(unittest.TestCase):
    def test_happy_path(self):
        path = [LifecycleState.DISCOVERED, LifecycleState.PROFILING,
                LifecycleState.ENRICHING, LifecycleState.GENERATED,
                LifecycleState.PENDING_VALIDATION, LifecycleState.VALIDATED,
                LifecycleState.ACTIVE]
        for current, nxt in zip(path, path[1:]):
            assert_transition(current, nxt)

    def test_stale_rebuild_cycle(self):
        assert_transition(LifecycleState.ACTIVE, LifecycleState.STALE)
        assert_transition(LifecycleState.STALE, LifecycleState.REBUILDING)
        assert_transition(LifecycleState.REBUILDING, LifecycleState.ACTIVE)

    def test_degraded_paths(self):
        assert_transition(LifecycleState.REBUILDING, LifecycleState.DEGRADED)
        assert_transition(LifecycleState.DEGRADED, LifecycleState.ACTIVE)

    def test_illegal_transition_rejected(self):
        with self.assertRaises(DatahekError) as cm:
            assert_transition(LifecycleState.DISCOVERED, LifecycleState.ACTIVE)
        self.assertEqual(cm.exception.code, ErrorCode.VALIDATION)

    def test_superseded_is_terminal(self):
        self.assertIn(LifecycleState.SUPERSEDED, TERMINAL_STATES)
        self.assertEqual(next_states(LifecycleState.SUPERSEDED), frozenset())
        with self.assertRaises(DatahekError):
            assert_transition(LifecycleState.SUPERSEDED, LifecycleState.ACTIVE)

    def test_is_transition_allowed(self):
        self.assertTrue(is_transition_allowed(LifecycleState.PROFILING, LifecycleState.FAILED))
        self.assertFalse(is_transition_allowed(LifecycleState.ENRICHING, LifecycleState.ACTIVE))

    def test_all_states_have_entries(self):
        for state in LifecycleState:
            self.assertIn(state, LEGAL_TRANSITIONS)


if __name__ == "__main__":
    unittest.main()
