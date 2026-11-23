import json
from pathlib import Path
from typing import Any, Callable

from contract_review.pipeline import (
    review_contract_v0,
    review_contract_v1,
)
from contract_review.metrics import (
    compute_aggregate_metrics,
    evidence_is_valid,
)


REPO_ROOT = Path(__file__).resolve().parents[2]

GROUND_TRUTH_PATH = (
    REPO_ROOT
    / "data"
    / "ground_truth.json"
)

CONTRACTS_DIR = (
    REPO_ROOT
    / "data"
    / "contracts"
)

RESULTS_DIR = (
    REPO_ROOT
    / "eval"
    / "results"
)


PIPELINES: dict[str, Callable] = {
    "v0": review_contract_v0,
    "v1": review_contract_v1,
}


def load_ground_truth() -> dict[str, Any]:
    return json.loads(
        GROUND_TRUTH_PATH.read_text(
            encoding="utf-8"
        )
    )


def contract_path_for(
    contract_id: str,
) -> Path:
    return CONTRACTS_DIR / f"{contract_id}.txt"


def evaluate(
    version: str,
) -> dict[str, Any]:

    if version not in PIPELINES:
        raise ValueError(
            f"Unsupported evaluation version: {version}"
        )

    pipeline = PIPELINES[version]
    ground_truth = load_ground_truth()

    contract_results: list[dict[str, Any]] = []

    for contract_id, contract_gt in (
        ground_truth["contracts"].items()
    ):
        contract_path = contract_path_for(contract_id)

        contract_text = contract_path.read_text(
            encoding="utf-8"
        )

        expected_findings = (
            contract_gt["expected_findings"]
        )

        try:
            review_result, metadata = pipeline(
                contract_text=contract_text,
                contract_source=str(contract_path),
            )

        except Exception as exc:
            # Preserve one result per expected rule
            # even if the entire contract review fails.
            rule_results = []

            for rule_id, expected in expected_findings.items():
                rule_results.append({
                    "rule_id": rule_id,
                    "review_success": False,
                    "expected_status": (
                        expected["expected_status"]
                    ),
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
                "rules": rule_results,
            })

            continue

        predictions_by_rule = {
            finding.rule_id: finding
            for finding in review_result.findings
        }

        rule_results = []

        for rule_id, expected in expected_findings.items():

            prediction = predictions_by_rule[rule_id]

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

            end_to_end_correct = (
                status_correct
                and human_review_correct
                and evidence_valid
            )

            rule_result = {
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

                "relevant_clause_ids": expected.get(
                    "relevant_clause_ids",
                    [],
                ),
                "expected_facts": expected.get(
                    "expected_facts",
                    [],
                ),

                "end_to_end_correct": end_to_end_correct,
            }

            # V1-specific diagnostics, without altering
            # any of the shared evaluation metrics.
            if version == "v1":
                evidence_checks = metadata.get(
                    "evidence_checks",
                    {}
                )

                rule_result["evidence_verification"] = (
                    evidence_checks.get(rule_id)
                )

            rule_results.append(rule_result)

        contract_results.append({
            "contract_id": contract_id,
            "contract_path": str(contract_path),
            "review_success": True,
            "error_type": None,
            "error": None,
            "latency_ms": metadata["latency_ms"],
            "usage": {
                "prompt_tokens": metadata["prompt_tokens"],
                "completion_tokens": (
                    metadata["completion_tokens"]
                ),
                "total_tokens": metadata["total_tokens"],
            },
            "request_id": metadata["request_id"],
            "model": metadata["model"],
            "finish_reason": metadata["finish_reason"],
            "generation_settings": (
                metadata["generation_settings"]
            ),
            "rules": rule_results,
        })

    aggregate_metrics = compute_aggregate_metrics(
        contract_results
    )

    return {
        "version": version,
        "dataset_version": ground_truth["dataset_version"],
        "ruleset": ground_truth["ruleset"],
        "metrics": aggregate_metrics,
        "contracts": contract_results,
    }


def save_results(
    result: dict[str, Any],
    version: str,
) -> Path:

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = RESULTS_DIR / f"{version}.json"

    output_path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    return output_path


def run_eval(
    version: str,
) -> tuple[dict[str, Any], Path]:

    result = evaluate(version)
    output_path = save_results(
        result=result,
        version=version,
    )

    return result, output_path


# Backward compatibility with the existing CLI.
def run_v0_eval() -> tuple[dict[str, Any], Path]:
    return run_eval("v0")


def run_v1_eval() -> tuple[dict[str, Any], Path]:
    return run_eval("v1")


if __name__ == "__main__":
    result, output_path = run_eval("v1")

    print(
        json.dumps(
            result["metrics"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"\nSaved results to {output_path}")
