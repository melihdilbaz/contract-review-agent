"""Evaluation runner for Contract Review Agent V2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from contract_review.metrics import (
    compute_aggregate_metrics,
    evidence_is_valid,
)
from contract_review.pipeline_v2 import review_contract_v2
from contract_review.run_eval import (
    CONTRACTS_DIR,
    GROUND_TRUTH_PATH,
    RESULTS_DIR,
)


V2_RESULTS_PATH = RESULTS_DIR / "v2.json"

RULE_IDS = {
    "R01", "R02", "R03",
    "R04", "R05", "R06",
}


def load_ground_truth() -> dict[str, Any]:
    return json.loads(
        GROUND_TRUTH_PATH.read_text(encoding="utf-8")
    )


def _failure_rules(
    expected_findings: dict[str, Any],
) -> list[dict[str, Any]]:

    return [
        {
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
            "relevant_clause_ids": expected.get(
                "relevant_clause_ids", []
            ),
            "candidate_recall": 0.0,
        }
        for rule_id, expected in expected_findings.items()
    ]


def _require_metadata(
    metadata: dict[str, Any],
) -> None:
    """Validate required successful-run artifacts."""

    required = (
        "candidate_extraction",
        "candidate_verification",
        "rule_evaluations",
        "usage",
        "latency_ms",
        "finish_reason",
    )

    missing = [
        key for key in required
        if key not in metadata
    ]

    if missing:
        raise RuntimeError(
            f"V2 metadata missing required fields: {missing}"
        )

    if metadata["finish_reason"] != "stop":
        raise RuntimeError(
            "V2 extraction did not finish normally"
        )

    for key in (
        "candidate_extraction",
        "candidate_verification",
        "rule_evaluations",
    ):
        if metadata[key] is None:
            raise RuntimeError(
                f"V2 metadata artifact is null: {key}"
            )

    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        if metadata["usage"].get(key) is None:
            raise RuntimeError(
                f"V2 usage missing: {key}"
            )


def evaluate_v2() -> dict[str, Any]:
    ground_truth = load_ground_truth()
    contract_results = []

    candidate_expected_total = 0
    candidate_detected_total = 0

    verified_candidate_total = 0
    valid_candidate_total = 0

    for contract_id, contract_gt in (
        ground_truth["contracts"].items()
    ):
        contract_path = (
            CONTRACTS_DIR / f"{contract_id}.txt"
        )

        contract_text = contract_path.read_text(
            encoding="utf-8"
        )

        expected_findings = (
            contract_gt["expected_findings"]
        )

        try:
            review_result, metadata = review_contract_v2(
                contract_text=contract_text,
                contract_source=str(contract_path),
            )

        except Exception as exc:
            contract_results.append({
                "contract_id": contract_id,
                "contract_path": str(contract_path),
                "review_success": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "latency_ms": None,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "rules": _failure_rules(
                    expected_findings
                ),
            })

            continue

        # Successful pipeline responses must satisfy
        # evaluation invariants. Do not silently repair.
        _require_metadata(metadata)

        predictions = {
            finding.rule_id: finding
            for finding in review_result.findings
        }

        if (
            len(review_result.findings) != 6
            or set(predictions) != RULE_IDS
        ):
            raise RuntimeError(
                f"{contract_id}: expected exactly "
                "six unique final findings"
            )

        extracted = metadata[
            "candidate_extraction"
        ]["candidates"]

        verified = metadata[
            "candidate_verification"
        ]

        evaluations = metadata[
            "rule_evaluations"
        ]

        if len(verified) != len(extracted):
            raise RuntimeError(
                f"{contract_id}: verification count mismatch"
            )

        if (
            len(evaluations) != 6
            or {item["rule_id"] for item in evaluations}
            != RULE_IDS
        ):
            raise RuntimeError(
                f"{contract_id}: invalid rule evaluations"
            )

        # Unique (rule_id, clause_id) pairs.
        extracted_pairs = {
            (item["rule_id"], item["clause_id"])
            for item in extracted
        }

        rule_results = []

        for rule_id, expected in (
            expected_findings.items()
        ):
            prediction = predictions[rule_id]

            status_correct = (
                prediction.status
                == expected["expected_status"]
            )

            human_review_correct = (
                prediction.requires_human_review
                == expected["requires_human_review"]
            )

            evidence_valid = evidence_is_valid(
                evidence=prediction.evidence,
                predicted_status=prediction.status,
                contract_text=contract_text,
            )

            relevant_ids = set(
                expected.get("relevant_clause_ids", [])
            )

            detected_ids = {
                clause_id
                for candidate_rule, clause_id
                in extracted_pairs
                if candidate_rule == rule_id
            }

            matched_ids = (
                relevant_ids & detected_ids
            )

            candidate_expected_total += len(
                relevant_ids
            )

            candidate_detected_total += len(
                matched_ids
            )

            rule_results.append({
                "rule_id": rule_id,
                "review_success": True,
                "expected_status": (
                    expected["expected_status"]
                ),
                "predicted_status": prediction.status,
                "status_correct": status_correct,
                "expected_requires_human_review": (
                    expected["requires_human_review"]
                ),
                "predicted_requires_human_review": (
                    prediction.requires_human_review
                ),
                "human_review_correct": (
                    human_review_correct
                ),
                "evidence": prediction.evidence,
                "evidence_valid": evidence_valid,
                "reason": prediction.reason,
                "relevant_clause_ids": sorted(
                    relevant_ids
                ),
                "extracted_clause_ids": sorted(
                    detected_ids
                ),
                "matched_clause_ids": sorted(
                    matched_ids
                ),
                "candidate_recall": (
                    len(matched_ids) / len(relevant_ids)
                    if relevant_ids
                    else 1.0
                ),
                "end_to_end_correct": (
                    status_correct
                    and human_review_correct
                    and evidence_valid
                ),
            })

        verified_candidate_total += len(verified)

        valid_candidate_total += sum(
            item["evidence_valid"]
            for item in verified
        )

        contract_results.append({
            "contract_id": contract_id,
            "contract_path": str(contract_path),
            "review_success": True,
            "error_type": None,
            "error": None,

            "latency_ms": metadata["latency_ms"],
            "usage": metadata["usage"],

            "request_id": metadata.get("request_id"),
            "model": metadata.get("model"),
            "finish_reason": metadata["finish_reason"],
            "generation_settings": metadata.get(
                "generation_settings"
            ),

            "extraction": metadata[
                "candidate_extraction"
            ],
            "candidate_verification": verified,
            "evaluations": evaluations,
            "final_findings": (
                review_result.model_dump(mode="json")
            ),
            "rules": rule_results,
        })

    # Reuse exact V0/V1 metric definitions.
    metrics = compute_aggregate_metrics(
        contract_results
    )

    # Failed contracts contribute their expected
    # clause IDs to the candidate-recall denominator.
    for contract in contract_results:
        if contract["review_success"]:
            continue

        expected_findings = ground_truth[
            "contracts"
        ][contract["contract_id"]]["expected_findings"]

        for expected in expected_findings.values():
            candidate_expected_total += len(
                set(expected.get("relevant_clause_ids", []))
            )

    metrics["candidate_recall"] = (
        candidate_detected_total
        / candidate_expected_total
        if candidate_expected_total
        else 1.0
    )

    metrics["candidate_evidence_validity"] = (
        valid_candidate_total
        / verified_candidate_total
        if verified_candidate_total
        else 0.0
    )

    metrics["v2_counts"] = {
        "expected_relevant_clauses": (
            candidate_expected_total
        ),
        "detected_relevant_clauses": (
            candidate_detected_total
        ),
        "verified_candidates": (
            verified_candidate_total
        ),
        "valid_candidate_evidence": (
            valid_candidate_total
        ),
    }

    gt_hash = hashlib.sha256(
        GROUND_TRUTH_PATH.read_bytes()
    ).hexdigest()

    return {
        "version": "v2",
        "dataset_version": ground_truth[
            "dataset_version"
        ],
        "ruleset": ground_truth["ruleset"],
        "ground_truth_sha256": gt_hash,
        "comparison_note": (
            "V0/V1 paired replay uses frozen LLM outputs. "
            "V2 uses a different extraction task and prompt. "
            "Therefore V0/V1 versus V2 is not a paired "
            "LLM comparison."
        ),
        "metrics": metrics,
        "contracts": contract_results,
    }


def run_v2_eval() -> tuple[dict[str, Any], Path]:
    result = evaluate_v2()

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    V2_RESULTS_PATH.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return result, V2_RESULTS_PATH


if __name__ == "__main__":
    result, output_path = run_v2_eval()

    print(
        json.dumps(
            result["metrics"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"\nSaved results to {output_path}")
