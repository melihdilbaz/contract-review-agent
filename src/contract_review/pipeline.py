import os
import time

from typing import Any
from uuid import uuid4

from contract_review.audit import append_event
from contract_review.llm import (
    call_llm,
    get_generation_settings,
)
from contract_review.metrics import evidence_is_valid
from contract_review.models import ReviewResult
from contract_review.prompts import build_v0_messages
from contract_review.rules import load_rules


def _review_contract(
    *,
    contract_text: str,
    contract_source: str | None,
    version: str,
    verify_evidence: bool,
) -> tuple[ReviewResult, dict[str, Any]]:

    run_id = uuid4().hex
    review_start = time.perf_counter()

    rules = load_rules()

    expected_rule_ids = {
        rule.rule_id
        for rule in rules
    }

    # V0 and V1 use exactly the same prompt.
    messages = build_v0_messages(
        contract_text=contract_text,
        rules=rules,
    )

    response_schema = ReviewResult.model_json_schema()

    llm_config = {
        "model": os.environ["LLM_MODEL"],
        "base_url": os.environ["LLM_BASE_URL"],
        "generation_settings": get_generation_settings(),
        "max_retries": 0,
    }

    append_event({
        "event": "llm_call_started",
        "run_id": run_id,
        "version": version,
        "contract_source": contract_source,
        "messages": messages,
        "response_schema": response_schema,
        "model": llm_config["model"],
        "base_url": llm_config["base_url"],
        "generation_settings": (
            llm_config["generation_settings"]
        ),
        "max_retries": llm_config["max_retries"],
    })

    # --------------------------------------------------
    # 1. LLM CALL
    # --------------------------------------------------

    llm_start = time.perf_counter()

    try:
        llm_response = call_llm(
            messages=messages,
            response_schema=response_schema,
        )

    except Exception as exc:
        latency_ms = round(
            (time.perf_counter() - llm_start) * 1000,
            2,
        )

        append_event({
            "event": "llm_call_failed",
            "run_id": run_id,
            "version": version,
            "contract_source": contract_source,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "latency_ms": latency_ms,
        })

        append_event({
            "event": "review_failed",
            "run_id": run_id,
            "version": version,
            "contract_source": contract_source,
            "stage": "llm_call",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "latency_ms": latency_ms,
        })

        raise

    # Record raw LLM output BEFORE validation.
    append_event({
        "event": "llm_call_completed",
        "run_id": run_id,
        "version": version,
        "contract_source": contract_source,
        "model": llm_response["model"],
        "request_id": llm_response["request_id"],
        "raw_response": llm_response["content"],
        "usage": {
            "prompt_tokens": (
                llm_response["prompt_tokens"]
            ),
            "completion_tokens": (
                llm_response["completion_tokens"]
            ),
            "total_tokens": (
                llm_response["total_tokens"]
            ),
        },
        "latency_ms": llm_response["latency_ms"],
        "finish_reason": llm_response["finish_reason"],
        "generation_settings": (
            llm_response["generation_settings"]
        ),
        "max_retries": llm_config["max_retries"],
    })

    # --------------------------------------------------
    # 2. RESPONSE VALIDATION
    # --------------------------------------------------

    try:
        finish_reason = llm_response["finish_reason"]
        content = llm_response["content"]

        if finish_reason != "stop":
            raise RuntimeError(
                "Incomplete LLM generation: "
                f"finish_reason={finish_reason!r}"
            )

        if not content:
            raise RuntimeError(
                "LLM returned empty response content."
            )

        review_result = ReviewResult.model_validate_json(
            content
        )

        actual_rule_ids = [
            finding.rule_id
            for finding in review_result.findings
        ]

        if len(actual_rule_ids) != len(expected_rule_ids):
            raise RuntimeError(
                f"Expected {len(expected_rule_ids)} "
                f"findings, received "
                f"{len(actual_rule_ids)}."
            )

        if len(set(actual_rule_ids)) != len(actual_rule_ids):
            raise RuntimeError(
                "LLM returned duplicate rule findings."
            )

        actual_rule_id_set = set(actual_rule_ids)

        if actual_rule_id_set != expected_rule_ids:
            missing = expected_rule_ids - actual_rule_id_set

            unexpected = (
                actual_rule_id_set - expected_rule_ids
            )

            raise RuntimeError(
                "LLM returned an invalid rule set. "
                f"Missing={sorted(missing)}, "
                f"Unexpected={sorted(unexpected)}."
            )

    except Exception as exc:
        append_event({
            "event": "review_failed",
            "run_id": run_id,
            "version": version,
            "contract_source": contract_source,
            "stage": "response_validation",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })

        raise

    # --------------------------------------------------
    # 3. V1-ONLY EXACT EVIDENCE VERIFICATION
    # --------------------------------------------------

    evidence_checks: dict[str, dict[str, Any]] = {}

    if verify_evidence:
        validated_findings = []

        for finding in review_result.findings:
            is_valid = evidence_is_valid(
                evidence=finding.evidence,
                predicted_status=finding.status,
                contract_text=contract_text,
            )

            original_human_review = (
                finding.requires_human_review
            )

            updated_human_review = (
                original_human_review or not is_valid
            )

            evidence_checks[finding.rule_id] = {
                "valid": is_valid,
                "evidence_valid": is_valid,
                "requires_human_review_before": (
                    original_human_review
                ),
                "requires_human_review_after": (
                    updated_human_review
                ),
                "escalated_due_to_evidence": (
                    not is_valid
                    and not original_human_review
                ),
            }

            # Preserve original LLM status and evidence.
            # Only escalate the human-review flag.
            updated_finding = finding.model_copy(
                update={
                    "requires_human_review": (
                        updated_human_review
                    )
                }
            )

            validated_findings.append(updated_finding)

            append_event({
                "event": "evidence_verification",
                "run_id": run_id,
                "version": version,
                "contract_source": contract_source,
                "rule_id": finding.rule_id,
                "status": finding.status,
                "evidence": finding.evidence,
                "evidence_valid": is_valid,
                "original_requires_human_review": (
                    original_human_review
                ),
                "final_requires_human_review": (
                    updated_human_review
                ),
                "escalated_due_to_evidence": (
                    not is_valid
                    and not original_human_review
                ),
            })

        review_result = review_result.model_copy(
            update={
                "findings": validated_findings
            }
        )

    # --------------------------------------------------
    # 4. FINDING AUDIT EVENTS
    # --------------------------------------------------

    for finding in review_result.findings:
        append_event({
            "event": "finding",
            "run_id": run_id,
            "version": version,
            "contract_source": contract_source,
            "rule_id": finding.rule_id,
            "status": finding.status,
            "requires_human_review": (
                finding.requires_human_review
            ),
            "evidence": finding.evidence,
            "reason": finding.reason,
        })

    # --------------------------------------------------
    # 5. REVIEW COMPLETED
    # --------------------------------------------------

    total_latency_ms = round(
        (time.perf_counter() - review_start) * 1000,
        2,
    )

    metadata = {
        "run_id": run_id,
        "version": version,
        "model": llm_response["model"],
        "request_id": llm_response["request_id"],
        "prompt_tokens": llm_response["prompt_tokens"],
        "completion_tokens": (
            llm_response["completion_tokens"]
        ),
        "total_tokens": llm_response["total_tokens"],
        "latency_ms": llm_response["latency_ms"],
        "total_review_latency_ms": total_latency_ms,
        "finish_reason": llm_response["finish_reason"],
        "generation_settings": (
            llm_response["generation_settings"]
        ),
        "max_retries": llm_config["max_retries"],
        "evidence_checks": evidence_checks,
    }

    append_event({
        "event": "review_completed",
        "run_id": run_id,
        "version": version,
        "contract_source": contract_source,
        "finding_count": len(review_result.findings),
        "latency_ms": total_latency_ms,
        "usage": {
            "prompt_tokens": (
                llm_response["prompt_tokens"]
            ),
            "completion_tokens": (
                llm_response["completion_tokens"]
            ),
            "total_tokens": (
                llm_response["total_tokens"]
            ),
        },
    })

    return review_result, metadata


# ------------------------------------------------------
# PUBLIC PIPELINE API
# ------------------------------------------------------

def review_contract_v0(
    contract_text: str,
    contract_source: str | None = None,
) -> tuple[ReviewResult, dict[str, Any]]:

    return _review_contract(
        contract_text=contract_text,
        contract_source=contract_source,
        version="v0",
        verify_evidence=False,
    )


def review_contract_v1(
    contract_text: str,
    contract_source: str | None = None,
) -> tuple[ReviewResult, dict[str, Any]]:

    return _review_contract(
        contract_text=contract_text,
        contract_source=contract_source,
        version="v1",
        verify_evidence=True,
    )
