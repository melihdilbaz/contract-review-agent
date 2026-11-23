import unittest

from contract_review.validation import (
    validate_evidence,
)


class EvidenceValidationTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.contract_text = (
            "A04 — Payment Terms\n"
            "Customer shall pay each valid invoice "
            "within forty-five (45) calendar days "
            "after receipt.\n\n"
            "A05 — Termination for Convenience\n"
            "Either party may terminate this "
            "Agreement upon forty-five (45) days' "
            "prior written notice."
        )

    def test_valid_exact_quote(self) -> None:
        quote = (
            "Customer shall pay each valid invoice "
            "within forty-five (45) calendar days "
            "after receipt."
        )

        result = validate_evidence(
            evidence=[quote],
            status="COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertTrue(result.valid)
        self.assertEqual(
            result.reason,
            "VALID",
        )
        self.assertEqual(
            result.invalid_quotes,
            (),
        )

    def test_invalid_quote(self) -> None:
        quote = (
            "Customer shall pay each valid invoice "
            "within thirty (30) calendar days "
            "after receipt."
        )

        result = validate_evidence(
            evidence=[quote],
            status="COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)
        self.assertEqual(
            result.reason,
            "QUOTE_NOT_FOUND",
        )
        self.assertEqual(
            result.invalid_quotes,
            (quote,),
        )

    def test_missing_quote_for_compliant(
        self,
    ) -> None:
        result = validate_evidence(
            evidence=[],
            status="COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)
        self.assertEqual(
            result.reason,
            "MISSING_REQUIRED_EVIDENCE",
        )

    def test_missing_quote_for_non_compliant(
        self,
    ) -> None:
        result = validate_evidence(
            evidence=[],
            status="NON_COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)
        self.assertEqual(
            result.reason,
            "MISSING_REQUIRED_EVIDENCE",
        )

    def test_not_found_allows_empty_evidence(
        self,
    ) -> None:
        result = validate_evidence(
            evidence=[],
            status="NOT_FOUND",
            contract_text=self.contract_text,
        )

        self.assertTrue(result.valid)
        self.assertEqual(
            result.reason,
            "VALID",
        )

    def test_not_found_with_valid_quote(
        self,
    ) -> None:
        quote = (
            "A04 — Payment Terms"
        )

        result = validate_evidence(
            evidence=[quote],
            status="NOT_FOUND",
            contract_text=self.contract_text,
        )

        self.assertTrue(result.valid)

    def test_not_found_with_invalid_quote(
        self,
    ) -> None:
        quote = (
            "This sentence does not exist."
        )

        result = validate_evidence(
            evidence=[quote],
            status="NOT_FOUND",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)
        self.assertEqual(
            result.reason,
            "QUOTE_NOT_FOUND",
        )

    def test_whitespace_difference_is_invalid(
        self,
    ) -> None:
        quote = (
            "A04 — Payment Terms "
            "Customer shall pay each valid invoice "
            "within forty-five (45) calendar days "
            "after receipt."
        )

        result = validate_evidence(
            evidence=[quote],
            status="COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)
        self.assertEqual(
            result.reason,
            "QUOTE_NOT_FOUND",
        )

    def test_all_quotes_must_be_valid(
        self,
    ) -> None:
        valid_quote = (
            "A04 — Payment Terms"
        )

        invalid_quote = (
            "Invented evidence."
        )

        result = validate_evidence(
            evidence=[
                valid_quote,
                invalid_quote,
            ],
            status="COMPLIANT",
            contract_text=self.contract_text,
        )

        self.assertFalse(result.valid)

        self.assertEqual(
            result.invalid_quotes,
            (invalid_quote,),
        )


if __name__ == "__main__":
    unittest.main()
