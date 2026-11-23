import pytest

from contract_review.models_v2 import V2CandidateExtractionResult
from contract_review.validation_v2 import verify_candidates_v2


CONTRACT = (
    "A05 — Termination\n"
    "Either party may terminate with 45 days notice.\n"
    "A06 — Security Termination\n"
    "The Security Schedule may be terminated immediately.\n"
)


def make_extraction(
    *,
    clause_id="A05",
    evidence=None,
    applicability="APPLICABLE",
):
    if evidence is None:
        evidence = [
            "Either party may terminate with 45 days notice."
        ]

    return V2CandidateExtractionResult.model_validate({
        "candidates": [{
            "rule_id": "R01",
            "clause_id": clause_id,
            "applicability": applicability,
            "evidence": evidence,
            "facts": {
                "notice_days": 45,
                "termination_type": "CONVENIENCE",
                "party_scope": "BOTH",
            },
        }]
    })


def test_valid_exact_evidence():
    result = verify_candidates_v2(
        extraction=make_extraction(),
        contract_text=CONTRACT,
    )

    assert len(result) == 1
    assert result[0].evidence_valid is True
    assert result[0].evidence_reason == "VALID"


def test_invalid_quote():
    result = verify_candidates_v2(
        extraction=make_extraction(
            evidence=["Payment is due within 90 days."]
        ),
        contract_text=CONTRACT,
    )

    assert result[0].evidence_valid is False
    assert result[0].evidence_reason == "QUOTE_NOT_FOUND"


def test_missing_evidence():
    result = verify_candidates_v2(
        extraction=make_extraction(evidence=[]),
        contract_text=CONTRACT,
    )

    assert result[0].evidence_valid is False
    assert (
        result[0].evidence_reason
        == "MISSING_REQUIRED_EVIDENCE"
    )


def test_not_applicable_candidate_preserved():
    result = verify_candidates_v2(
        extraction=make_extraction(
            clause_id="A06",
            applicability="NOT_APPLICABLE",
            evidence=[
                "The Security Schedule may be terminated immediately."
            ],
        ),
        contract_text=CONTRACT,
    )

    assert len(result) == 1
    assert result[0].evidence_valid is True
    assert (
        result[0].candidate.applicability
        == "NOT_APPLICABLE"
    )


def test_multiple_candidates_preserved():
    extraction = V2CandidateExtractionResult.model_validate({
        "candidates": [
            {
                "rule_id": "R01",
                "clause_id": "A05",
                "applicability": "APPLICABLE",
                "evidence": [
                    "Either party may terminate with 45 days notice."
                ],
                "facts": {
                    "notice_days": 45,
                    "termination_type": "CONVENIENCE",
                    "party_scope": "BOTH",
                },
            },
            {
                "rule_id": "R01",
                "clause_id": "A06",
                "applicability": "NOT_APPLICABLE",
                "evidence": [
                    "The Security Schedule may be terminated immediately."
                ],
                "facts": {
                    "notice_days": None,
                    "termination_type": "SECURITY",
                    "party_scope": "BOTH",
                },
            },
        ]
    })

    result = verify_candidates_v2(
        extraction=extraction,
        contract_text=CONTRACT,
    )

    assert len(result) == 2
    assert all(item.evidence_valid for item in result)
    assert {
        item.candidate.clause_id
        for item in result
    } == {"A05", "A06"}


def test_valid_quote_does_not_validate_fact_semantics():
    """
    Exact grounding is independent of extracted fact correctness.
    """

    extraction = make_extraction()

    # Deliberately incorrect fact; quote still matches.
    extraction.candidates[0].facts.notice_days = 90

    result = verify_candidates_v2(
        extraction=extraction,
        contract_text=CONTRACT,
    )

    assert result[0].evidence_valid is True
    assert result[0].candidate.facts.notice_days == 90
