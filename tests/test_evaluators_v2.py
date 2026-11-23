"""
Unit tests for V2 deterministic rule evaluators.

These tests do not call the LLM.

They verify:
- Deterministic numeric comparisons
- Rule-specific policy decisions
- Multi-candidate aggregation
- Missing facts handling
- Invalid evidence safety
- Ambiguous applicability
- NOT_APPLICABLE exclusion

Evidence verification results are simulated.
"""

import pytest

from contract_review.models_v2 import (
    V2CandidateExtractionResult,
    V2VerifiedCandidate,
    V2RuleEvaluatorInput,
)

from contract_review.evaluators_v2 import (
    evaluate_r01,
    evaluate_r02,
    evaluate_r03,
    evaluate_r04,
    evaluate_r05,
    evaluate_r06,
    evaluate_rule_v2,
)


# ============================================================
# Shared test helpers
# ============================================================

def make_candidate(
    rule_id,
    clause_id,
    facts,
    applicability="APPLICABLE",
    evidence_valid=True,
):
    """
    Create one typed candidate and wrap it in evidence
    verification metadata.

    No actual contract text verification occurs here.
    """

    evidence = f"Test evidence for {clause_id}"

    extraction = V2CandidateExtractionResult.model_validate({
        "candidates": [
            {
                "rule_id": rule_id,
                "clause_id": clause_id,
                "applicability": applicability,
                "evidence": [evidence],
                "facts": facts,
            }
        ]
    })

    candidate = extraction.candidates[0]

    return V2VerifiedCandidate(
        candidate=candidate,
        evidence_valid=evidence_valid,
        evidence_reason=(
            "VALID"
            if evidence_valid
            else "QUOTE_NOT_FOUND"
        ),
        invalid_quotes=(
            []
            if evidence_valid
            else [evidence]
        ),
    )


def evaluate(rule_id, candidates):
    """
    Evaluate one rule through the V2 dispatcher.
    """

    return evaluate_rule_v2(
        V2RuleEvaluatorInput(
            rule_id=rule_id,
            candidates=candidates,
        )
    )


# ============================================================
# R01 — Termination Notice
# ============================================================

@pytest.mark.parametrize(
    "notice_days,expected_status",
    [
        (45, "COMPLIANT"),
        (30, "COMPLIANT"),
        (15, "NON_COMPLIANT"),
    ],
)
def test_r01_numeric_comparison(
    notice_days,
    expected_status,
):

    candidate = make_candidate(
        rule_id="R01",
        clause_id="A05",
        facts={
            "notice_days": notice_days,
            "termination_type": "CONVENIENCE",
            "party_scope": "BOTH",
        },
    )

    result = evaluate_r01(
        V2RuleEvaluatorInput(
            rule_id="R01",
            candidates=[candidate],
        )
    )

    assert result.status == expected_status
    assert result.requires_human_review is False
    assert result.evaluated_clause_ids == ["A05"]


def test_r01_ambiguous_applicability():

    general_clause = make_candidate(
        rule_id="R01",
        clause_id="C05",
        facts={
            "notice_days": 45,
            "termination_type": "CONVENIENCE",
            "party_scope": "BOTH",
        },
    )

    security_clause = make_candidate(
        rule_id="R01",
        clause_id="C06",
        applicability="AMBIGUOUS",
        facts={
            "notice_days": 15,
            "termination_type": "SECURITY",
            "party_scope": "BOTH",
        },
    )

    result = evaluate(
        "R01",
        [general_clause, security_clause],
    )

    assert result.status == "COMPLIANT"
    assert result.requires_human_review is True

    assert set(result.evaluated_clause_ids) == {
        "C05",
        "C06",
    }

    assert result.reason_code == "AMBIGUOUS_APPLICABILITY"


def test_r01_not_applicable_exclusion():

    applicable = make_candidate(
        rule_id="R01",
        clause_id="A05",
        facts={
            "notice_days": 45,
            "termination_type": "CONVENIENCE",
            "party_scope": "BOTH",
        },
    )

    excluded = make_candidate(
        rule_id="R01",
        clause_id="A06",
        applicability="NOT_APPLICABLE",
        facts={
            "notice_days": 10,
            "termination_type": "SECURITY",
            "party_scope": "BOTH",
        },
    )

    result = evaluate(
        "R01",
        [applicable, excluded],
    )

    assert result.status == "COMPLIANT"
    assert result.requires_human_review is False

    assert result.evaluated_clause_ids == ["A05"]
    assert result.excluded_clause_ids == ["A06"]


# ============================================================
# R02 — Payment Terms
# ============================================================

@pytest.mark.parametrize(
    "payment_days,expected_status",
    [
        (45, "COMPLIANT"),
        (60, "COMPLIANT"),
        (90, "NON_COMPLIANT"),
    ],
)
def test_r02_numeric_comparison(
    payment_days,
    expected_status,
):

    candidate = make_candidate(
        rule_id="R02",
        clause_id="A04",
        facts={
            "payment_days": payment_days,
            "trigger_event": "INVOICE_RECEIPT",
            "invoice_scope": "VALID_SUPPLIER_INVOICE",
        },
    )

    result = evaluate_r02(
        V2RuleEvaluatorInput(
            rule_id="R02",
            candidates=[candidate],
        )
    )

    assert result.status == expected_status
    assert result.requires_human_review is False


def test_r02_invalid_evidence():

    candidate = make_candidate(
        rule_id="R02",
        clause_id="B04",
        evidence_valid=False,
        facts={
            "payment_days": 90,
            "trigger_event": "INVOICE_RECEIPT",
            "invoice_scope": "VALID_SUPPLIER_INVOICE",
        },
    )

    result = evaluate(
        "R02",
        [candidate],
    )

    assert result.status == "NOT_FOUND"
    assert result.requires_human_review is True

    assert (
        result.reason_code
        == "UNVERIFIED_CANDIDATE_EVIDENCE"
    )

    assert "B04" in result.evaluated_clause_ids

    # Invalid evidence must not be promoted to final evidence.
    assert result.evidence == []


# ============================================================
# R03 — Liability Cap
# ============================================================

def make_liability_candidates(
    contract_fees,
    liability_cap,
    prefix="A",
):

    fee_candidate = make_candidate(
        rule_id="R03",
        clause_id=f"{prefix}03",
        facts={
            "fact_type": "CONTRACT_FEES",
            "amount": contract_fees,
            "currency": "TRY",
            "fee_basis": "total contract fees",
        },
    )

    cap_candidate = make_candidate(
        rule_id="R03",
        clause_id=f"{prefix}07",
        facts={
            "fact_type": "LIABILITY_CAP",
            "cap_kind": "FIXED_AMOUNT",
            "cap_amount": liability_cap,
            "currency": "TRY",
            "fee_multiple": None,
            "fee_period_months": None,
            "liability_scope": "aggregate liability",
        },
    )

    return [fee_candidate, cap_candidate]


@pytest.mark.parametrize(
    "contract_fees,liability_cap,expected_status",
    [
        (120000, 100000, "COMPLIANT"),
        (100000, 100000, "COMPLIANT"),
        (100000, 200000, "NON_COMPLIANT"),
    ],
)
def test_r03_liability_comparison(
    contract_fees,
    liability_cap,
    expected_status,
):

    candidates = make_liability_candidates(
        contract_fees,
        liability_cap,
    )

    result = evaluate_r03(
        V2RuleEvaluatorInput(
            rule_id="R03",
            candidates=candidates,
        )
    )

    assert result.status == expected_status
    assert result.requires_human_review is False

    assert set(result.evaluated_clause_ids) == {
        "A03",
        "A07",
    }


def test_r03_missing_contract_fees():

    fee_candidate = make_candidate(
        rule_id="R03",
        clause_id="C03",
        facts={
            "fact_type": "CONTRACT_FEES",
            "amount": None,
            "currency": "TRY",
            "fee_basis": None,
        },
    )

    cap_candidate = make_candidate(
        rule_id="R03",
        clause_id="C07",
        facts={
            "fact_type": "LIABILITY_CAP",
            "cap_kind": "FEE_PERIOD",
            "cap_amount": None,
            "currency": "TRY",
            "fee_multiple": None,
            "fee_period_months": 12,
            "liability_scope": (
                "fees paid during preceding 12 months"
            ),
        },
    )

    result = evaluate(
        "R03",
        [fee_candidate, cap_candidate],
    )

    assert result.status == "NOT_FOUND"
    assert result.requires_human_review is True

    assert (
        result.reason_code
        == "INSUFFICIENT_EVALUABLE_FACTS"
    )


# ============================================================
# R04 — Governing Law
# ============================================================

def test_r04_multi_clause_aggregation():

    main_agreement = make_candidate(
        rule_id="R04",
        clause_id="C09",
        facts={
            "governing_law": "Republic of Türkiye",
            "governed_scope": "Agreement",
            "scope_kind": "MAIN_AGREEMENT",
        },
    )

    security_schedule = make_candidate(
        rule_id="R04",
        clause_id="C10",
        facts={
            "governing_law": "Germany",
            "governed_scope": "Security Schedule",
            "scope_kind": "SCHEDULE",
        },
    )

    result = evaluate_r04(
        V2RuleEvaluatorInput(
            rule_id="R04",
            candidates=[
                main_agreement,
                security_schedule,
            ],
        )
    )

    assert result.status == "NON_COMPLIANT"
    assert result.requires_human_review is True

    assert set(result.evaluated_clause_ids) == {
        "C09",
        "C10",
    }

    assert len(result.evidence) == 2

    assert result.reason_code == "POLICY_VIOLATION"


# ============================================================
# R05 — Mutual Confidentiality
# ============================================================

@pytest.mark.parametrize(
    (
        "customer_obligated,"
        "supplier_obligated,"
        "customer_exclusion,"
        "expected_status"
    ),
    [
        (True, True, False, "COMPLIANT"),
        (False, True, True, "NON_COMPLIANT"),
    ],
)
def test_r05_mutual_confidentiality(
    customer_obligated,
    supplier_obligated,
    customer_exclusion,
    expected_status,
):

    candidate = make_candidate(
        rule_id="R05",
        clause_id="B07",
        facts={
            "obligation_present": True,
            "customer_obligated": customer_obligated,
            "supplier_obligated": supplier_obligated,
            "explicit_customer_exclusion": customer_exclusion,
            "explicit_supplier_exclusion": False,
            "information_category": None,
            "is_general_confidentiality_obligation": True,
        },
    )

    result = evaluate_r05(
        V2RuleEvaluatorInput(
            rule_id="R05",
            candidates=[candidate],
        )
    )

    assert result.status == expected_status
    assert result.requires_human_review is False


# ============================================================
# R06 — Automatic Renewal
# ============================================================

@pytest.mark.parametrize(
    "mechanism,auto_renewal,expected_status,expected_review",
    [
        (
            "AFFIRMATIVE_MUTUAL_AGREEMENT",
            False,
            "COMPLIANT",
            False,
        ),
        (
            "AUTOMATIC",
            True,
            "NON_COMPLIANT",
            False,
        ),
        (
            "CONTINUED_PERFORMANCE",
            None,
            "NOT_FOUND",
            True,
        ),
    ],
)
def test_r06_renewal_mechanisms(
    mechanism,
    auto_renewal,
    expected_status,
    expected_review,
):

    candidate = make_candidate(
        rule_id="R06",
        clause_id="C13",
        facts={
            "renewal_mechanism": mechanism,
            "auto_renewal_present": auto_renewal,
            "explicit_no_auto_renewal": (
                True
                if mechanism == "AFFIRMATIVE_MUTUAL_AGREEMENT"
                else None
            ),
            "affirmative_action_required": (
                True
                if mechanism == "AFFIRMATIVE_MUTUAL_AGREEMENT"
                else None
            ),
            "renewal_period_months": None,
            "opt_out_notice_days": None,
        },
    )

    result = evaluate_r06(
        V2RuleEvaluatorInput(
            rule_id="R06",
            candidates=[candidate],
        )
    )

    assert result.status == expected_status

    assert (
        result.requires_human_review
        == expected_review
    )


# ============================================================
# Dispatcher
# ============================================================

def test_dispatcher_returns_one_result():

    candidate = make_candidate(
        rule_id="R01",
        clause_id="A05",
        facts={
            "notice_days": 45,
            "termination_type": "CONVENIENCE",
            "party_scope": "BOTH",
        },
    )

    result = evaluate(
        "R01",
        [candidate],
    )

    assert result.rule_id == "R01"
    assert result.status == "COMPLIANT"
