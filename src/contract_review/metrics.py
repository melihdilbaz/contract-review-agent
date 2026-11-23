from typing import Any

from contract_review.validation import (
    validate_evidence,
)


def evidence_is_valid(
    *,
    evidence: list[str],
    predicted_status: str,
    contract_text: str,
) -> bool:
    return validate_evidence(
        evidence=evidence,
        status=predicted_status,
        contract_text=contract_text,
    ).valid


def compute_aggregate_metrics(
    contract_results: list[dict[str, Any]],
) -> dict[str, Any]:
    total_contracts = len(
        contract_results
    )

    successful_contracts = sum(
        1
        for contract in contract_results
        if contract["review_success"]
    )

    all_rule_results = [
        rule
        for contract in contract_results
        for rule in contract["rules"]
    ]

    successful_rule_results = [
        rule
        for contract in contract_results
        if contract["review_success"]
        for rule in contract["rules"]
    ]

    classification_total = len(
        successful_rule_results
    )

    classification_correct = sum(
        1
        for rule in successful_rule_results
        if rule["status_correct"]
    )

    classification_accuracy = (
        classification_correct
        / classification_total
        if classification_total
        else 0.0
    )

    expected_violations = [
        rule
        for rule in all_rule_results
        if (
            rule["expected_status"]
            == "NON_COMPLIANT"
        )
    ]

    detected_violations = sum(
        1
        for rule in expected_violations
        if (
            rule["review_success"]
            and rule["predicted_status"]
            == "NON_COMPLIANT"
        )
    )

    violation_recall = (
        detected_violations
        / len(expected_violations)
        if expected_violations
        else 1.0
    )

    expected_human_reviews = [
        rule
        for rule in all_rule_results
        if rule[
            "expected_requires_human_review"
        ]
    ]

    detected_human_reviews = sum(
        1
        for rule in expected_human_reviews
        if (
            rule["review_success"]
            and rule[
                "predicted_requires_human_review"
            ]
            is True
        )
    )

    human_review_recall = (
        detected_human_reviews
        / len(expected_human_reviews)
        if expected_human_reviews
        else 1.0
    )

    valid_evidence_findings = sum(
        1
        for rule in successful_rule_results
        if rule["evidence_valid"]
    )

    exact_evidence_quote_validity = (
        valid_evidence_findings
        / len(successful_rule_results)
        if successful_rule_results
        else 0.0
    )

    successful_review_coverage = (
        successful_contracts
        / total_contracts
        if total_contracts
        else 0.0
    )

    end_to_end_correct = sum(
        1
        for rule in all_rule_results
        if rule["end_to_end_correct"]
    )

    end_to_end_correct_prediction_rate = (
        end_to_end_correct
        / len(all_rule_results)
        if all_rule_results
        else 0.0
    )

    successful_contract_results = [
        contract
        for contract in contract_results
        if contract["review_success"]
    ]

    total_prompt_tokens = sum(
        contract["usage"]["prompt_tokens"]
        for contract
        in successful_contract_results
    )

    total_completion_tokens = sum(
        contract["usage"][
            "completion_tokens"
        ]
        for contract
        in successful_contract_results
    )

    total_tokens = sum(
        contract["usage"]["total_tokens"]
        for contract
        in successful_contract_results
    )

    total_latency_ms = sum(
        contract["latency_ms"]
        for contract
        in successful_contract_results
    )

    successful_count = len(
        successful_contract_results
    )

    return {
        "classification_accuracy": (
            classification_accuracy
        ),
        "violation_recall": violation_recall,
        "exact_evidence_quote_validity": (
            exact_evidence_quote_validity
        ),
        "human_review_recall": (
            human_review_recall
        ),
        "successful_review_coverage": (
            successful_review_coverage
        ),
        "end_to_end_correct_prediction_rate": (
            end_to_end_correct_prediction_rate
        ),
        "counts": {
            "contracts_total": total_contracts,
            "contracts_successful": (
                successful_contracts
            ),
            "rules_total": len(
                all_rule_results
            ),
            "rules_successfully_predicted": (
                len(successful_rule_results)
            ),
            "classification_correct": (
                classification_correct
            ),
            "expected_violations": len(
                expected_violations
            ),
            "detected_violations": (
                detected_violations
            ),
            "expected_human_reviews": len(
                expected_human_reviews
            ),
            "detected_human_reviews": (
                detected_human_reviews
            ),
            "end_to_end_correct": (
                end_to_end_correct
            ),
        },
        "usage": {
            "prompt_tokens_total": (
                total_prompt_tokens
            ),
            "completion_tokens_total": (
                total_completion_tokens
            ),
            "total_tokens": total_tokens,
            "latency_ms_total": (
                total_latency_ms
            ),
            "latency_ms_average": (
                total_latency_ms
                / successful_count
                if successful_count
                else None
            ),
            "tokens_per_contract_average": (
                total_tokens
                / successful_count
                if successful_count
                else None
            ),
        },
    }
