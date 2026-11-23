"""V2 candidate extraction and deterministic evaluator data contracts.

Evidence validity means verbatim grounding only, not semantic correctness.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from contract_review.models import FindingStatus


# ============================================================
# Shared types
# ============================================================

V2RuleId = Literal[
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
]

V2Applicability = Literal[
    "APPLICABLE",
    "NOT_APPLICABLE",
    "AMBIGUOUS",
]

V2EvidenceReason = Literal[
    "VALID",
    "MISSING_REQUIRED_EVIDENCE",
    "QUOTE_NOT_FOUND",
]


class V2StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ============================================================
# Typed facts
#
# Extracted by LLM.
# Not yet semantically verified.
# ============================================================

class V2TerminationFacts(V2StrictModel):

    notice_days: int | None = Field(
        default=None,
        ge=0,
    )

    termination_type: Literal[
        "CONVENIENCE",
        "BREACH",
        "SECURITY",
        "REGULATORY",
        "OTHER",
        "UNKNOWN",
    ] | None = None

    party_scope: Literal[
        "CUSTOMER",
        "SUPPLIER",
        "BOTH",
        "UNKNOWN",
    ] | None = None


class V2PaymentFacts(V2StrictModel):

    payment_days: int | None = Field(
        default=None,
        ge=0,
    )

    trigger_event: Literal[
        "INVOICE_RECEIPT",
        "INVOICE_APPROVAL",
        "SERVICE_ACCEPTANCE",
        "OTHER",
        "UNKNOWN",
    ] | None = None

    invoice_scope: Literal[
        "VALID_SUPPLIER_INVOICE",
        "OTHER",
        "UNKNOWN",
    ] | None = None


# ============================================================
# R03 — Liability facts
#
# CONTRACT_FEES and LIABILITY_CAP must remain separate.
# fact_type is REQUIRED for union discrimination.
# ============================================================

class V2ContractFeesFacts(V2StrictModel):

    fact_type: Literal["CONTRACT_FEES"]

    amount: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    currency: str | None = None

    fee_basis: str | None = None


class V2LiabilityCapFacts(V2StrictModel):

    fact_type: Literal["LIABILITY_CAP"]

    cap_kind: Literal[
        "FIXED_AMOUNT",
        "FEE_MULTIPLE",
        "FEE_PERIOD",
        "UNLIMITED",
        "OTHER",
        "UNKNOWN",
    ] | None = None

    cap_amount: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    currency: str | None = None

    fee_multiple: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    fee_period_months: int | None = Field(
        default=None,
        ge=0,
    )

    liability_scope: str | None = None


V2LiabilityFacts: TypeAlias = Annotated[
    V2ContractFeesFacts | V2LiabilityCapFacts,
    Field(discriminator="fact_type"),
]


# ============================================================
# R04 — Governing law
# ============================================================

class V2GoverningLawFacts(V2StrictModel):

    governing_law: str | None = None

    governed_scope: str | None = None

    scope_kind: Literal[
        "MAIN_AGREEMENT",
        "SCHEDULE",
        "ANNEX",
        "SOW",
        "OTHER",
        "UNKNOWN",
    ] | None = None


# ============================================================
# R05 — Confidentiality
# ============================================================

class V2ConfidentialityFacts(V2StrictModel):

    obligation_present: bool | None = None

    customer_obligated: bool | None = None

    supplier_obligated: bool | None = None

    explicit_customer_exclusion: bool | None = None

    explicit_supplier_exclusion: bool | None = None

    information_category: str | None = None

    is_general_confidentiality_obligation: bool | None = None


# ============================================================
# R06 — Renewal
# ============================================================

class V2RenewalFacts(V2StrictModel):

    renewal_mechanism: Literal[
        "AUTOMATIC",
        "AFFIRMATIVE_MUTUAL_AGREEMENT",
        "CONTINUED_PERFORMANCE",
        "EXPLICIT_NO_RENEWAL",
        "OTHER",
        "UNKNOWN",
    ] | None = None

    auto_renewal_present: bool | None = None

    explicit_no_auto_renewal: bool | None = None

    affirmative_action_required: bool | None = None

    renewal_period_months: int | None = Field(
        default=None,
        ge=0,
    )

    opt_out_notice_days: int | None = Field(
        default=None,
        ge=0,
    )


# ============================================================
# Candidate models
#
# rule_id is REQUIRED.
#
# No default values on discriminator fields.
# ============================================================

class V2CandidateBase(V2StrictModel):

    clause_id: str = Field(min_length=1)

    applicability: V2Applicability

    evidence: list[str]


class V2TerminationCandidate(V2CandidateBase):

    rule_id: Literal["R01"]

    facts: V2TerminationFacts


class V2PaymentCandidate(V2CandidateBase):

    rule_id: Literal["R02"]

    facts: V2PaymentFacts


class V2LiabilityCandidate(V2CandidateBase):

    rule_id: Literal["R03"]

    facts: V2LiabilityFacts


class V2GoverningLawCandidate(V2CandidateBase):

    rule_id: Literal["R04"]

    facts: V2GoverningLawFacts


class V2ConfidentialityCandidate(V2CandidateBase):

    rule_id: Literal["R05"]

    facts: V2ConfidentialityFacts


class V2RenewalCandidate(V2CandidateBase):

    rule_id: Literal["R06"]

    facts: V2RenewalFacts


# ============================================================
# Discriminated candidate union
#
# A single rule may have multiple candidates.
# ============================================================

V2Candidate: TypeAlias = Annotated[
    V2TerminationCandidate
    | V2PaymentCandidate
    | V2LiabilityCandidate
    | V2GoverningLawCandidate
    | V2ConfidentialityCandidate
    | V2RenewalCandidate,
    Field(discriminator="rule_id"),
]


# ============================================================
# Extraction result
# ============================================================

class V2CandidateExtractionResult(V2StrictModel):
    """
    One LLM response.

    Multiple candidates per rule are allowed.
    """

    candidates: list[V2Candidate]


# ============================================================
# Verified candidate
#
# Evidence validation confirms exact text grounding only.
# It does not guarantee fact correctness.
# ============================================================

class V2VerifiedCandidate(V2StrictModel):

    candidate: V2Candidate

    evidence_valid: bool

    evidence_reason: V2EvidenceReason

    invalid_quotes: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def check_verification_consistency(
        self,
    ) -> V2VerifiedCandidate:

        if self.evidence_valid != (
            self.evidence_reason == "VALID"
        ):
            raise ValueError(
                "evidence_valid must match evidence_reason"
            )

        if self.evidence_valid and self.invalid_quotes:
            raise ValueError(
                "valid evidence cannot have invalid_quotes"
            )

        return self


# ============================================================
# Rule evaluator input
#
# Preserve all extracted candidates, including:
#
# - APPLICABLE
# - NOT_APPLICABLE
# - AMBIGUOUS
# - invalid evidence
# ============================================================

class V2RuleEvaluatorInput(V2StrictModel):

    rule_id: V2RuleId

    candidates: list[V2VerifiedCandidate]

    @model_validator(mode="after")
    def check_candidate_rule_ids(
        self,
    ) -> V2RuleEvaluatorInput:

        if any(
            item.candidate.rule_id != self.rule_id
            for item in self.candidates
        ):
            raise ValueError(
                "every candidate must match evaluator rule_id"
            )

        return self


# ============================================================
# Deterministic rule evaluation output
#
# Exactly one result per rule.
# ============================================================

class V2RuleEvaluation(V2StrictModel):

    rule_id: V2RuleId

    status: FindingStatus

    requires_human_review: bool

    evidence: list[str]

    reason: str

    reason_code: str | None = None

    evaluated_clause_ids: list[str] = Field(
        default_factory=list,
    )

    excluded_clause_ids: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def check_clause_sets(
        self,
    ) -> V2RuleEvaluation:

        evaluated = set(self.evaluated_clause_ids)

        excluded = set(self.excluded_clause_ids)

        if evaluated & excluded:
            raise ValueError(
                "evaluated and excluded clause IDs must not overlap"
            )

        return self
