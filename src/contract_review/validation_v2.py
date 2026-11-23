"""
V2 candidate-level evidence verification.

Reuses V1 exact evidence validation.

Evidence validity confirms verbatim grounding only.
It does not prove semantic correctness of extracted facts.
"""

from contract_review.models_v2 import (
    V2CandidateExtractionResult,
    V2VerifiedCandidate,
)
from contract_review.validation import validate_evidence


def verify_candidates_v2(
    *,
    extraction: V2CandidateExtractionResult,
    contract_text: str,
) -> list[V2VerifiedCandidate]:
    """
    Verify all extracted candidates without filtering any out.

    NOT_APPLICABLE and AMBIGUOUS candidates are preserved.
    """

    verified_candidates = []

    for candidate in extraction.candidates:

        # Candidates are extracted clauses, not final findings.
        # Every candidate must have valid quoted evidence.
        result = validate_evidence(
            evidence=candidate.evidence,
            status="COMPLIANT",
            contract_text=contract_text,
        )

        verified_candidates.append(
            V2VerifiedCandidate(
                candidate=candidate,
                evidence_valid=result.valid,
                evidence_reason=result.reason,
                invalid_quotes=list(result.invalid_quotes),
            )
        )

    return verified_candidates
