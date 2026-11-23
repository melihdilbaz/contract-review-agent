from dataclasses import dataclass
from typing import Literal

from contract_review.models import FindingStatus


EvidenceValidationReason = Literal[
    "VALID",
    "MISSING_REQUIRED_EVIDENCE",
    "QUOTE_NOT_FOUND",
]


@dataclass(frozen=True)
class EvidenceValidationResult:
    valid: bool
    reason: EvidenceValidationReason
    invalid_quotes: tuple[str, ...] = ()


def validate_evidence(
    *,
    evidence: list[str],
    status: FindingStatus,
    contract_text: str,
) -> EvidenceValidationResult:
    """
    Deterministically verify evidence against the original contract.

    Rules:
    - COMPLIANT and NON_COMPLIANT require at least one evidence quote.
    - Every provided quote must occur verbatim in the contract.
    - NOT_FOUND may have an empty evidence list.
    - If NOT_FOUND contains evidence, those quotes must still be exact.
    """

    if not evidence:
        if status == "NOT_FOUND":
            return EvidenceValidationResult(
                valid=True,
                reason="VALID",
            )

        return EvidenceValidationResult(
            valid=False,
            reason="MISSING_REQUIRED_EVIDENCE",
        )

    invalid_quotes = tuple(
        quote
        for quote in evidence
        if quote not in contract_text
    )

    if invalid_quotes:
        return EvidenceValidationResult(
            valid=False,
            reason="QUOTE_NOT_FOUND",
            invalid_quotes=invalid_quotes,
        )

    return EvidenceValidationResult(
        valid=True,
        reason="VALID",
    )
