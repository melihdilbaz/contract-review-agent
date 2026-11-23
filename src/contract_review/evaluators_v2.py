from collections.abc import Iterable

from contract_review.models_v2 import (
    V2Candidate,
    V2ConfidentialityCandidate,
    V2ContractFeesFacts,
    V2GoverningLawCandidate,
    V2LiabilityCandidate,
    V2LiabilityCapFacts,
    V2PaymentCandidate,
    V2RenewalCandidate,
    V2RuleEvaluation,
    V2RuleEvaluatorInput,
    V2TerminationCandidate,
    V2VerifiedCandidate,
)


# =========================================================
# Shared helpers
# =========================================================


def _clause_ids(
    candidates: Iterable[V2VerifiedCandidate],
) -> list[str]:
    result: list[str] = []

    for verified in candidates:
        clause_id = verified.candidate.clause_id

        if clause_id is None:
            continue

        if clause_id not in result:
            result.append(clause_id)

    return result


def _evidence(
    candidates: Iterable[V2VerifiedCandidate],
) -> list[str]:
    """
    Return unique evidence only from candidates whose exact
    evidence verification succeeded.

    evidence_valid=True means only that the quoted text occurs
    verbatim in the contract. It does NOT imply that the
    extracted structured facts are semantically correct.
    """

    result: list[str] = []

    for verified in candidates:
        if not verified.evidence_valid:
            continue

        for quote in verified.candidate.evidence:
            if quote not in result:
                result.append(quote)

    return result


def _partition(
    evaluator_input: V2RuleEvaluatorInput,
) -> tuple[
    list[V2VerifiedCandidate],
    list[V2VerifiedCandidate],
    list[V2VerifiedCandidate],
    list[V2VerifiedCandidate],
]:
    """
    Returns:
        applicable_verified
        ambiguous_verified
        not_applicable
        unverified_relevant

    In V2:
    - NOT_APPLICABLE candidates are excluded from final policy
      calculation.
    - They remain available for audit/diagnostics.
    - AMBIGUOUS candidates are retained separately.
    - Evidence-invalid candidates are not trusted as factual
      inputs for deterministic evaluation.
    """

    applicable_verified: list[V2VerifiedCandidate] = []
    ambiguous_verified: list[V2VerifiedCandidate] = []
    not_applicable: list[V2VerifiedCandidate] = []
    unverified_relevant: list[V2VerifiedCandidate] = []

    for verified in evaluator_input.candidates:
        candidate = verified.candidate

        if candidate.applicability == "NOT_APPLICABLE":
            not_applicable.append(verified)
            continue

        if not verified.evidence_valid:
            unverified_relevant.append(verified)
            continue

        if candidate.applicability == "APPLICABLE":
            applicable_verified.append(verified)
            continue

        if candidate.applicability == "AMBIGUOUS":
            ambiguous_verified.append(verified)
            continue

        raise ValueError(
            "Unsupported applicability: "
            f"{candidate.applicability}"
        )

    return (
        applicable_verified,
        ambiguous_verified,
        not_applicable,
        unverified_relevant,
   )

def _build_evaluation(
    *,
    evaluator_input: V2RuleEvaluatorInput,
    status: str,
    requires_human_review: bool,
    decision_code: str,
    reason: str,
    considered: list[V2VerifiedCandidate],
    ambiguous: list[V2VerifiedCandidate],
    not_applicable: list[V2VerifiedCandidate],
    unverified: list[V2VerifiedCandidate],
) -> V2RuleEvaluation:
    """
    Convert evaluator decisions into the existing V2RuleEvaluation schema.

    All original candidates remain available in evaluator_input.
    This output records which clauses were considered or excluded.
    """

    # Candidates actively considered by the evaluator.
    evaluated_ids = list(
        dict.fromkeys(
            _clause_ids(considered)
            + _clause_ids(ambiguous)
            + _clause_ids(unverified)
        )
    )

    # NOT_APPLICABLE candidates are excluded from the final decision.
    excluded_ids = list(
        dict.fromkeys(_clause_ids(not_applicable))
    )

    # Preserve the model invariant:
    # evaluated_clause_ids and excluded_clause_ids must not overlap.
    excluded_set = set(excluded_ids)

    evaluated_ids = [
        clause_id
        for clause_id in evaluated_ids
        if clause_id not in excluded_set
    ]

    return V2RuleEvaluation(
        rule_id=evaluator_input.rule_id,
        status=status,
        requires_human_review=requires_human_review,
        evidence=_evidence(considered),
        reason=reason,
        reason_code=decision_code,
        evaluated_clause_ids=evaluated_ids,
        excluded_clause_ids=excluded_ids,
    )

# =========================================================
# R01 — Termination Notice
#
# Policy:
# General termination for convenience requires at least
# 30 days' prior written notice.
#
# Numeric comparison is deterministic Python logic.
# =========================================================


def evaluate_r01(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R01":
        raise ValueError(
            "evaluate_r01 requires rule_id='R01'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    relevant: list[V2VerifiedCandidate] = []

    for verified in applicable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2TerminationCandidate,
        ):
            raise TypeError(
                "R01 received non-termination candidate"
            )

        if candidate.facts.termination_type == "CONVENIENCE":
            relevant.append(verified)

    # A verified, applicable convenience clause below the
    # threshold is enough to establish a violation.
    violating = [
        verified
        for verified in relevant
        if (
            verified.candidate.facts.notice_days
            is not None
            and verified.candidate.facts.notice_days < 30
        )
    ]

    if violating:
        considered = relevant

        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one applicable termination-for-"
                "convenience clause provides fewer than "
                "30 days of prior notice."
            ),
            considered=considered,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    missing_notice = [
        verified
        for verified in relevant
        if verified.candidate.facts.notice_days is None
    ]

    if missing_notice:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "A relevant termination-for-convenience "
                "clause was found, but its notice period "
                "could not be evaluated."
            ),
            considered=relevant,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if relevant:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "All verified applicable termination-for-"
                "convenience clauses provide at least "
                "30 days of prior notice."
            ),
            considered=relevant,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="UNVERIFIED_CANDIDATE_EVIDENCE",
            reason=(
                "Potentially relevant termination facts "
                "were extracted, but their evidence could "
                "not be verified exactly."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if ambiguous:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="AMBIGUOUS_APPLICABILITY",
            reason=(
                "Termination candidates were found, but "
                "their applicability to the convenience "
                "termination policy is ambiguous."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=False,
        decision_code="NO_RELEVANT_CANDIDATE",
        reason=(
            "No applicable termination-for-convenience "
            "candidate was found."
        ),
        considered=[],
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# R02 — Payment Terms
#
# Policy:
# Valid supplier invoices must be payable no later than
# 60 calendar days after receipt.
# =========================================================


def evaluate_r02(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R02":
        raise ValueError(
            "evaluate_r02 requires rule_id='R02'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    relevant: list[V2VerifiedCandidate] = []

    for verified in applicable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2PaymentCandidate,
        ):
            raise TypeError(
                "R02 received non-payment candidate"
            )

        facts = candidate.facts

        if (
            facts.invoice_scope
            == "VALID_SUPPLIER_INVOICE"
            and facts.trigger_event
            == "INVOICE_RECEIPT"
        ):
            relevant.append(verified)

    violating = [
        verified
        for verified in relevant
        if (
            verified.candidate.facts.payment_days
            is not None
            and verified.candidate.facts.payment_days > 60
        )
    ]

    if violating:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one applicable payment clause "
                "allows more than 60 calendar days after "
                "receipt of a valid supplier invoice."
            ),
            considered=relevant,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    missing_days = [
        verified
        for verified in relevant
        if verified.candidate.facts.payment_days is None
    ]

    if missing_days:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "A relevant payment clause was found, but "
                "the payment period could not be evaluated."
            ),
            considered=relevant,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if relevant:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "All verified applicable payment clauses "
                "require payment within 60 calendar days "
                "after receipt of a valid supplier invoice."
            ),
            considered=relevant,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="UNVERIFIED_CANDIDATE_EVIDENCE",
            reason=(
                "Potentially relevant payment facts were "
                "extracted, but their evidence could not "
                "be verified exactly."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if ambiguous:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="AMBIGUOUS_APPLICABILITY",
            reason=(
                "Payment candidates were found, but their "
                "applicability to the payment policy is "
                "ambiguous."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=False,
        decision_code="NO_RELEVANT_CANDIDATE",
        reason="No applicable payment candidate was found.",
        considered=[],
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# R03 — Liability Cap
#
# Policy:
# Applicable aggregate liability cap must not exceed total
# contract fees.
#
# V2 only performs deterministic comparison when a fixed
# liability amount and a concrete contract fee amount are
# available in the same currency.
# =========================================================


def evaluate_r03(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R03":
        raise ValueError(
            "evaluate_r03 requires rule_id='R03'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    fee_candidates: list[V2VerifiedCandidate] = []
    cap_candidates: list[V2VerifiedCandidate] = []

    for verified in applicable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2LiabilityCandidate,
        ):
            raise TypeError(
                "R03 received non-liability candidate"
            )

        if isinstance(
            candidate.facts,
            V2ContractFeesFacts,
        ):
            fee_candidates.append(verified)

        elif isinstance(
            candidate.facts,
            V2LiabilityCapFacts,
        ):
            cap_candidates.append(verified)

        else:
            raise TypeError(
                "Unsupported R03 facts type"
            )

    concrete_fees = [
        verified
        for verified in fee_candidates
        if (
            verified.candidate.facts.amount is not None
            and verified.candidate.facts.currency is not None
        )
    ]

    # Multiple incompatible contract fee amounts make the
    # comparison basis ambiguous.
    distinct_fees = {
        (
            verified.candidate.facts.amount,
            verified.candidate.facts.currency,
        )
        for verified in concrete_fees
    }

    if len(distinct_fees) > 1:
        considered = fee_candidates + cap_candidates

        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="CONFLICTING_CLAUSES",
            reason=(
                "Multiple conflicting contract fee values "
                "were extracted, so a single deterministic "
                "liability comparison cannot be made."
            ),
            considered=considered,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if not concrete_fees:
        if unverified and not fee_candidates:
            code = "UNVERIFIED_CANDIDATE_EVIDENCE"
        else:
            code = "INSUFFICIENT_EVALUABLE_FACTS"

        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code=code,
            reason=(
                "No verified concrete aggregate contract "
                "fee is available for deterministic "
                "liability-cap comparison."
            ),
            considered=fee_candidates + cap_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    fee_verified = concrete_fees[0]
    fee_facts = fee_verified.candidate.facts

    assert isinstance(
        fee_facts,
        V2ContractFeesFacts,
    )
    assert fee_facts.amount is not None
    assert fee_facts.currency is not None

    comparable_caps: list[V2VerifiedCandidate] = []
    unresolved_caps: list[V2VerifiedCandidate] = []

    for verified in cap_candidates:
        facts = verified.candidate.facts

        assert isinstance(
            facts,
            V2LiabilityCapFacts,
        )

        if (
            facts.cap_kind == "FIXED_AMOUNT"
            and facts.cap_amount is not None
            and facts.currency is not None
            and facts.currency == fee_facts.currency
        ):
            comparable_caps.append(verified)
        else:
            unresolved_caps.append(verified)

    violating = [
        verified
        for verified in comparable_caps
        if (
            verified.candidate.facts.cap_amount
            is not None
            and verified.candidate.facts.cap_amount
            > fee_facts.amount
        )
    ]

    considered = (
        [fee_verified]
        + comparable_caps
        + unresolved_caps
    )

    if violating:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous
                or unverified
                or unresolved_caps
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one verified fixed aggregate "
                "liability cap exceeds the verified total "
                "contract fees."
            ),
            considered=considered,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unresolved_caps:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "Liability clauses were found, but at "
                "least one applicable cap cannot be "
                "deterministically compared with total "
                "contract fees."
            ),
            considered=considered,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if comparable_caps:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "All verified comparable aggregate "
                "liability caps are less than or equal to "
                "the verified total contract fees."
            ),
            considered=considered,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        code = "UNVERIFIED_CANDIDATE_EVIDENCE"
    else:
        code = "INSUFFICIENT_EVALUABLE_FACTS"

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=True,
        decision_code=code,
        reason=(
            "No verified liability cap can be "
            "deterministically compared with the contract "
            "fees."
        ),
        considered=considered,
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# R04 — Governing Law
#
# Policy:
# Main agreement and incorporated schedules/annexes must be
# governed by the Republic of Türkiye.
#
# For V2, an AMBIGUOUS schedule candidate can establish a
# potential policy violation, but the final result must also
# require human review.
# =========================================================


def _is_turkiye_law(
    value: str | None,
) -> bool | None:
    if value is None:
        return None

    normalized = (
        value.casefold()
        .replace("ü", "u")
        .strip()
    )

    accepted = {
        "republic of turkiye",
        "turkiye",
        "turkish law",
        "laws of the republic of turkiye",
        "law of the republic of turkiye",
    }

    return normalized in accepted


def evaluate_r04(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R04":
        raise ValueError(
            "evaluate_r04 requires rule_id='R04'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    # R04 is intentionally special:
    #
    # An ambiguous incorporated scope with explicit foreign
    # governing law is sufficient for NON_COMPLIANT, while
    # ambiguity keeps requires_human_review=True.
    evaluable = applicable + ambiguous

    governing_candidates: list[
        V2VerifiedCandidate
    ] = []

    unknown_law: list[V2VerifiedCandidate] = []

    foreign_law: list[V2VerifiedCandidate] = []

    for verified in evaluable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2GoverningLawCandidate,
        ):
            raise TypeError(
                "R04 received non-governing-law candidate"
            )

        governing_candidates.append(verified)

        is_turkiye = _is_turkiye_law(
            candidate.facts.governing_law
        )

        if is_turkiye is None:
            unknown_law.append(verified)

        elif not is_turkiye:
            foreign_law.append(verified)

    # Different applicable governing-law scopes may create
    # interpretation and precedence questions.
    turkish_law = [
        verified
        for verified in governing_candidates
        if _is_turkiye_law(
            verified.candidate.facts.governing_law
        ) is True
    ]

    conflicting_scopes = bool(
        foreign_law and turkish_law
    )

    if foreign_law:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified or conflicting_scopes
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one verified governing-law "
                "candidate for the agreement or an "
                "incorporated scope specifies law other "
                "than the Republic of Türkiye."
            ),
            considered=governing_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unknown_law:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "A governing-law candidate was found, but "
                "its governing law could not be determined."
            ),
            considered=governing_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if governing_candidates:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "All verified evaluable governing-law "
                "candidates specify the Republic of "
                "Türkiye."
            ),
            considered=governing_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="UNVERIFIED_CANDIDATE_EVIDENCE",
            reason=(
                "Potential governing-law facts were "
                "extracted, but their evidence could not "
                "be verified exactly."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=False,
        decision_code="NO_RELEVANT_CANDIDATE",
        reason="No governing-law candidate was found.",
        considered=[],
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# R05 — Confidentiality
#
# Policy:
# Confidentiality obligations must apply to both Customer
# and Supplier.
#
# LLM performs semantic extraction of which party is bound.
# Python performs the final both-parties aggregation.
# =========================================================


def evaluate_r05(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R05":
        raise ValueError(
            "evaluate_r05 requires rule_id='R05'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    general: list[V2VerifiedCandidate] = []

    for verified in applicable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2ConfidentialityCandidate,
        ):
            raise TypeError(
                "R05 received non-confidentiality candidate"
            )

        facts = candidate.facts

        category = (
            (facts.information_category or "")
            .strip()
            .upper()
        )

        is_general_obligation = (
            facts.is_general_confidentiality_obligation is True
        )

        has_explicit_exclusion = (
            facts.explicit_customer_exclusion is True
            or facts.explicit_supplier_exclusion is True
        )

        is_general_exclusion = (
            has_explicit_exclusion
            and category in {
                "CONFIDENTIAL_INFORMATION",
                "ALL_CONFIDENTIAL_INFORMATION",
            }
        )

        if is_general_obligation or is_general_exclusion:
            general.append(verified)

    # Explicit general exclusion of either party is a clear
    # violation.
    explicit_violation = [
        verified
        for verified in general
        if (
            verified.candidate.facts
            .explicit_customer_exclusion
            or verified.candidate.facts
            .explicit_supplier_exclusion
            or verified.candidate.facts.customer_obligated
            is False
            or verified.candidate.facts.supplier_obligated
            is False
        )
    ]

    if explicit_violation:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one applicable general "
                "confidentiality clause explicitly leaves "
                "Customer or Supplier without the required "
                "confidentiality obligation."
            ),
            considered=general,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    mutual = [
        verified
        for verified in general
        if (
            verified.candidate.facts.customer_obligated
            is True
            and verified.candidate.facts.supplier_obligated
            is True
        )
    ]

    incomplete = [
        verified
        for verified in general
        if (
            verified.candidate.facts.customer_obligated
            is None
            or verified.candidate.facts.supplier_obligated
            is None
        )
    ]

    if incomplete:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "A general confidentiality clause was "
                "found, but the obligations of both parties "
                "could not be determined."
            ),
            considered=general,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if mutual:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "Verified applicable general "
                "confidentiality obligations bind both "
                "Customer and Supplier."
            ),
            considered=general,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="UNVERIFIED_CANDIDATE_EVIDENCE",
            reason=(
                "Potential confidentiality facts were "
                "extracted, but their evidence could not "
                "be verified exactly."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if ambiguous:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="AMBIGUOUS_APPLICABILITY",
            reason=(
                "Confidentiality candidates were found, "
                "but their applicability is ambiguous."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=False,
        decision_code="NO_RELEVANT_CANDIDATE",
        reason=(
            "No applicable general confidentiality "
            "candidate was found."
        ),
        considered=[],
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# R06 — Automatic Renewal
#
# Policy:
# Agreement must not automatically renew.
# Renewal requires affirmative agreement/action.
# =========================================================


def evaluate_r06(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id != "R06":
        raise ValueError(
            "evaluate_r06 requires rule_id='R06'"
        )

    (
        applicable,
        ambiguous,
        not_applicable,
        unverified,
    ) = _partition(evaluator_input)

    renewal_candidates: list[
        V2VerifiedCandidate
    ] = []

    for verified in applicable:
        candidate = verified.candidate

        if not isinstance(
            candidate,
            V2RenewalCandidate,
        ):
            raise TypeError(
                "R06 received non-renewal candidate"
            )

        renewal_candidates.append(verified)

    violating = [
        verified
        for verified in renewal_candidates
        if (
            verified.candidate.facts.auto_renewal_present
            is True
            or verified.candidate.facts.renewal_mechanism
            == "AUTOMATIC"
        )
    ]

    if violating:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NON_COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code="POLICY_VIOLATION",
            reason=(
                "At least one applicable renewal clause "
                "provides for automatic renewal."
            ),
            considered=renewal_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    unresolved = [
        verified
        for verified in renewal_candidates
        if (
            verified.candidate.facts.renewal_mechanism
            in {
                "CONTINUED_PERFORMANCE",
                "OTHER",
                "UNKNOWN",
                None,
            }
            and (
                verified.candidate.facts
                .explicit_no_auto_renewal
                is not True
            )
        )
    ]

    if unresolved:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="INSUFFICIENT_EVALUABLE_FACTS",
            reason=(
                "A renewal-related mechanism was found, "
                "but it does not establish whether renewal "
                "is automatic or requires affirmative "
                "action."
            ),
            considered=renewal_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    compliant = [
        verified
        for verified in renewal_candidates
        if (
            (
                verified.candidate.facts
                .explicit_no_auto_renewal
                is True
                and verified.candidate.facts
                .affirmative_action_required
                is True
            )
            or (
                verified.candidate.facts.renewal_mechanism
                == "AFFIRMATIVE_MUTUAL_AGREEMENT"
            )
        )
    ]

    if compliant:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="COMPLIANT",
            requires_human_review=bool(
                ambiguous or unverified
            ),
            decision_code=(
                "AMBIGUOUS_APPLICABILITY"
                if ambiguous
                else "POLICY_SATISFIED"
            ),
            reason=(
                "Verified applicable renewal provisions "
                "do not provide for automatic renewal and "
                "require affirmative action or agreement."
            ),
            considered=renewal_candidates,
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if unverified:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="UNVERIFIED_CANDIDATE_EVIDENCE",
            reason=(
                "Potential renewal facts were extracted, "
                "but their evidence could not be verified "
                "exactly."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    if ambiguous:
        return _build_evaluation(
            evaluator_input=evaluator_input,
            status="NOT_FOUND",
            requires_human_review=True,
            decision_code="AMBIGUOUS_APPLICABILITY",
            reason=(
                "Renewal candidates were found, but their "
                "applicability is ambiguous."
            ),
            considered=[],
            ambiguous=ambiguous,
            not_applicable=not_applicable,
            unverified=unverified,
        )

    return _build_evaluation(
        evaluator_input=evaluator_input,
        status="NOT_FOUND",
        requires_human_review=False,
        decision_code="NO_RELEVANT_CANDIDATE",
        reason="No applicable renewal candidate was found.",
        considered=[],
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        unverified=unverified,
    )


# =========================================================
# Dispatcher
# =========================================================


def evaluate_rule_v2(
    evaluator_input: V2RuleEvaluatorInput,
) -> V2RuleEvaluation:
    if evaluator_input.rule_id == "R01":
        return evaluate_r01(evaluator_input)

    if evaluator_input.rule_id == "R02":
        return evaluate_r02(evaluator_input)

    if evaluator_input.rule_id == "R03":
        return evaluate_r03(evaluator_input)

    if evaluator_input.rule_id == "R04":
        return evaluate_r04(evaluator_input)

    if evaluator_input.rule_id == "R05":
        return evaluate_r05(evaluator_input)

    if evaluator_input.rule_id == "R06":
        return evaluate_r06(evaluator_input)

    raise ValueError(
        f"Unsupported V2 rule: {evaluator_input.rule_id}"
    )