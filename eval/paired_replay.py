import json
from pathlib import Path
from collections import Counter

from contract_review.models import ReviewResult
from contract_review.validation import validate_evidence
from contract_review.metrics import compute_aggregate_metrics


REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURE_PATH = (
    REPO_ROOT / "eval/fixtures/v0_raw_responses.json"
)

GROUND_TRUTH_PATH = (
    REPO_ROOT / "data/ground_truth.json"
)

V0_BASELINE_PATH = (
    REPO_ROOT / "eval/results/v0.json"
)

OUTPUT_PATH = (
    REPO_ROOT / "eval/results/paired_v0_v1.json"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay_contract(
    contract_id,
    fixture,
    ground_truth,
    version,
):
    contract_path = (
        REPO_ROOT / "data/contracts" / f"{contract_id}.txt"
    )

    contract_text = contract_path.read_text(encoding="utf-8")

    expected_findings = ground_truth["expected_findings"]

    raw_response = fixture["raw_response"]

    rule_results = []
    verification_results = []

    try:
        # Same Pydantic validation used by the live pipeline.
        review_result = ReviewResult.model_validate_json(
            raw_response
        )

        expected_rule_ids = set(expected_findings)

        actual_rule_ids = [
            finding.rule_id
            for finding in review_result.findings
        ]

        # Preserve the original structural validation behavior.
        if len(actual_rule_ids) != len(expected_rule_ids):
            raise RuntimeError(
                f"Expected {len(expected_rule_ids)} "
                f"findings, received {len(actual_rule_ids)}."
            )

        if len(set(actual_rule_ids)) != len(actual_rule_ids):
            raise RuntimeError(
                "LLM returned duplicate rule findings."
            )

        if set(actual_rule_ids) != expected_rule_ids:
            raise RuntimeError(
                "LLM returned an invalid rule set."
            )

    except Exception as exc:

        for rule_id, expected in expected_findings.items():
            rule_results.append({
                "rule_id": rule_id,
                "review_success": False,
                "expected_status": expected["expected_status"],
                "predicted_status": None,
                "status_correct": False,
                "expected_requires_human_review": (
                    expected["requires_human_review"]
                ),
                "predicted_requires_human_review": None,
                "human_review_correct": False,
                "evidence": [],
                "evidence_valid": False,
                "end_to_end_correct": False,
            })

        return {
            "contract_id": contract_id,
            "review_success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "latency_ms": None,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "rules": rule_results,
        }, verification_results

    predictions = {
        finding.rule_id: finding
        for finding in review_result.findings
    }

    for rule_id, expected in expected_findings.items():

        prediction = predictions[rule_id]

        original_status = prediction.status
        original_evidence = list(prediction.evidence)
        original_reason = prediction.reason
        original_human_review = (
            prediction.requires_human_review
        )

        check = validate_evidence(
            evidence=prediction.evidence,
            status=prediction.status,
            contract_text=contract_text,
        )

        # V1-only post-processing.
        if version == "v1" and not check.valid:
            prediction = prediction.model_copy(
                update={
                    "requires_human_review": True
                }
            )

        # The verifier must never rewrite semantic decisions.
        assert prediction.status == original_status
        assert prediction.evidence == original_evidence
        assert prediction.reason == original_reason

        status_correct = (
            prediction.status == expected["expected_status"]
        )

        human_review_correct = (
            prediction.requires_human_review
            == expected["requires_human_review"]
        )

        evidence_valid = check.valid

        end_to_end_correct = (
            status_correct
            and human_review_correct
            and evidence_valid
        )

        rule_results.append({
            "rule_id": rule_id,
            "review_success": True,
            "expected_status": expected["expected_status"],
            "predicted_status": prediction.status,
            "status_correct": status_correct,
            "expected_requires_human_review": (
                expected["requires_human_review"]
            ),
            "predicted_requires_human_review": (
                prediction.requires_human_review
            ),
            "human_review_correct": human_review_correct,
            "evidence": prediction.evidence,
            "evidence_valid": evidence_valid,
            "reason": prediction.reason,
            "end_to_end_correct": end_to_end_correct,
        })

        verification_results.append({
            "contract_id": contract_id,
            "rule_id": rule_id,
            "evidence_valid": check.valid,
            "verification_reason": check.reason,
            "human_review_before": original_human_review,
            "human_review_after": (
                prediction.requires_human_review
            ),
            "escalated_due_to_evidence": (
                version == "v1"
                and not check.valid
                and not original_human_review
            ),
        })

    usage = fixture.get("usage") or {}

    return {
        "contract_id": contract_id,
        "review_success": True,
        "error_type": None,
        "error": None,
        "latency_ms": fixture.get("latency_ms"),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens") or 0,
            "completion_tokens": (
                usage.get("completion_tokens") or 0
            ),
            "total_tokens": usage.get("total_tokens") or 0,
        },
        "rules": rule_results,
    }, verification_results


def evaluate_replay(version, fixture_data, ground_truth):

    results = []
    verification_results = []

    fixture_contracts = fixture_data["contracts"]
    expected_contracts = ground_truth["contracts"]

    assert set(fixture_contracts) == set(expected_contracts)

    for contract_id, contract_gt in expected_contracts.items():

        result, checks = replay_contract(
            contract_id=contract_id,
            fixture=fixture_contracts[contract_id],
            ground_truth=contract_gt,
            version=version,
        )

        results.append(result)
        verification_results.extend(checks)

    metrics = compute_aggregate_metrics(results)

    return {
        "version": version,
        "metrics": metrics,
        "contracts": results,
        "verification_results": verification_results,
    }


def main():

    assert not OUTPUT_PATH.exists(), (
        "Paired results already exist; refusing to overwrite."
    )

    fixture_data = load_json(FIXTURE_PATH)
    ground_truth = load_json(GROUND_TRUTH_PATH)
    baseline = load_json(V0_BASELINE_PATH)

    v0 = evaluate_replay(
        "v0",
        fixture_data,
        ground_truth,
    )

    v1 = evaluate_replay(
        "v1",
        fixture_data,
        ground_truth,
    )

    # Replay must reproduce the frozen V0 baseline.
    shared_metrics = [
        "classification_accuracy",
        "violation_recall",
        "exact_evidence_quote_validity",
        "human_review_recall",
        "successful_review_coverage",
        "end_to_end_correct_prediction_rate",
    ]

    for metric in shared_metrics:
        assert abs(
            v0["metrics"][metric]
            - baseline["metrics"][metric]
        ) < 1e-9, (
            f"V0 replay mismatch: {metric}"
        )

        # Evidence verification must not alter these metrics.
        if metric in {
            "classification_accuracy",
            "violation_recall",
            "exact_evidence_quote_validity",
            "successful_review_coverage",
        }:
            assert abs(
                v0["metrics"][metric]
                - v1["metrics"][metric]
            ) < 1e-9, (
                f"Unexpected V0/V1 difference: {metric}"
            )

    # Check all unchanged semantic fields.
    for contract_v0, contract_v1 in zip(
        v0["contracts"],
        v1["contracts"],
    ):
        assert (
            contract_v0["contract_id"]
            == contract_v1["contract_id"]
        )

        assert (
            contract_v0["review_success"]
            == contract_v1["review_success"]
        )

        for rule_v0, rule_v1 in zip(
            contract_v0["rules"],
            contract_v1["rules"],
        ):
            for field in (
                "rule_id",
                "predicted_status",
                "status_correct",
                "evidence",
                "evidence_valid",
                "reason",
            ):
                assert (
                    rule_v0.get(field)
                    == rule_v1.get(field)
                ), (
                    f"Unexpected semantic change: {field}"
                )

    invalid_checks = [
        check
        for check in v1["verification_results"]
        if not check["evidence_valid"]
    ]

    escalations = [
        check
        for check in invalid_checks
        if check["escalated_due_to_evidence"]
    ]

    diagnostics = {
        "invalid_evidence_count": len(invalid_checks),
        "evidence_escalation_count": len(escalations),
        "invalid_evidence_escalation_rate": (
            len(escalations) / len(invalid_checks)
            if invalid_checks
            else None
        ),
    }

    output = {
        "experiment": "paired_v0_v1_replay",
        "source": fixture_data["source"],
        "dataset_version": ground_truth["dataset_version"],
        "v0": v0,
        "v1": v1,
        "v1_diagnostics": diagnostics,
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    print("Paired replay evaluation: PASS")

    print(
        json.dumps(
            {
                "v0_metrics": v0["metrics"],
                "v1_metrics": v1["metrics"],
                "v1_diagnostics": diagnostics,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"\nSaved results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
