"""Provenance and trust authority rules (ADR-008, ADR-013)."""
import unittest

from datahek.contracts.context import ProvenanceSource, TrustLevel, ValidationStatus
from datahek.context.provenance import (
    TRUST_ORDER,
    can_override,
    effective_trust,
    is_authoritative,
    trust_for,
)


class TestProvenance(unittest.TestCase):
    def test_trust_order(self):
        self.assertGreater(TRUST_ORDER[TrustLevel.SYSTEM], TRUST_ORDER[TrustLevel.VALIDATED])
        self.assertGreater(TRUST_ORDER[TrustLevel.VALIDATED], TRUST_ORDER[TrustLevel.STRUCTURAL])
        self.assertGreater(TRUST_ORDER[TrustLevel.STRUCTURAL], TRUST_ORDER[TrustLevel.PROPOSED])
        self.assertGreater(TRUST_ORDER[TrustLevel.PROPOSED], TRUST_ORDER[TrustLevel.UNTRUSTED])

    def test_effective_trust_is_minimum(self):
        self.assertEqual(
            effective_trust([TrustLevel.STRUCTURAL, TrustLevel.UNTRUSTED, TrustLevel.VALIDATED]),
            TrustLevel.UNTRUSTED,
        )
        self.assertEqual(effective_trust([]), TrustLevel.UNTRUSTED)

    def test_authoritative_levels(self):
        self.assertTrue(is_authoritative(TrustLevel.SYSTEM))
        self.assertTrue(is_authoritative(TrustLevel.VALIDATED))
        self.assertTrue(is_authoritative(TrustLevel.STRUCTURAL))
        self.assertFalse(is_authoritative(TrustLevel.PROPOSED))
        self.assertFalse(is_authoritative(TrustLevel.UNTRUSTED))

    def test_human_validation_overrides_llm(self):
        self.assertTrue(can_override(TrustLevel.VALIDATED, TrustLevel.PROPOSED))
        self.assertTrue(can_override(TrustLevel.VALIDATED, TrustLevel.STRUCTURAL))
        self.assertFalse(can_override(TrustLevel.PROPOSED, TrustLevel.VALIDATED))

    def test_structurally_equal_does_not_override(self):
        self.assertFalse(can_override(TrustLevel.STRUCTURAL, TrustLevel.STRUCTURAL))

    def test_trust_for(self):
        self.assertEqual(trust_for(ProvenanceSource.DATABASE, ValidationStatus.NOT_REQUIRED),
                         TrustLevel.STRUCTURAL)
        self.assertEqual(trust_for(ProvenanceSource.SYSTEM, ValidationStatus.NOT_REQUIRED),
                         TrustLevel.SYSTEM)
        self.assertEqual(trust_for(ProvenanceSource.LLM, ValidationStatus.PENDING),
                         TrustLevel.PROPOSED)
        self.assertEqual(trust_for(ProvenanceSource.LLM, ValidationStatus.APPROVED),
                         TrustLevel.VALIDATED)
        self.assertEqual(trust_for(ProvenanceSource.HUMAN_VALIDATED, ValidationStatus.APPROVED),
                         TrustLevel.VALIDATED)
        self.assertEqual(trust_for(ProvenanceSource.USER, ValidationStatus.PENDING),
                         TrustLevel.PROPOSED)
        self.assertEqual(trust_for(ProvenanceSource.IMPORTED, ValidationStatus.NOT_REQUIRED),
                         TrustLevel.PROPOSED)
        self.assertEqual(trust_for(ProvenanceSource.INFERRED, ValidationStatus.NOT_REQUIRED),
                         TrustLevel.UNTRUSTED)


if __name__ == "__main__":
    unittest.main()
