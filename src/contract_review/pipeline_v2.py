"""
V2 contract review pipeline.

Architecture:
    Contract
      -> Batched LLM candidate extraction
      -> Pydantic schema validation
      -> Candidate-level exact evidence verification
      -> Deterministic rule evaluation
      -> Six final findings

This module does not modify existing V0/V1 pipelines.
"""

from __future__ import annotations

from typing import Any

from contract_review.models import (
    Finding,
    ReviewResult,
    Rule,
)

from contract_review.models_v2 import (
    V2CandidateExtractionResult,
    V2RuleEvaluatorInput,
    V2VerifiedCandidate,
)

from contract_review.prompts_v2 import build_v2_messages
from contract_review.validation_v2 import verify_candidates_v2
from contract_review.evaluators_v2 import evaluate_rule_v2

from contract_review.llm import call_llm

V2_MAX_TOKENS = 4096

V2_RULE_IDS = (
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
)


# ============================================================
# Rule loading
# ============================================================

def load_v2_rules() -> list[Rule]:
    """
    Load the existing ruleset without changing V0/V1.

    Uses the canonical config/rules.json file.
    """

    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]

    rules_path = repo_root / "config" / "rules.json"

    data = json.loads(
        rules_path.read_text(encoding="utf-8")
    )

    # Support both a direct rule list and a wrapped ruleset.
    if isinstance(data, list):
        rules_data = data

    elif isinstance(data, dict) and isinstance(
        data.get("rules"), list
    ):
        rules_data = data["rules"]

    else:
        raise ValueError(
            "Unsupported config/rules.json structure."
        )

    rules = [
        Rule.model_validate(item)
        for item in rules_data
    ]

    actual_ids = [rule.rule_id for rule in rules]

    if (
        len(actual_ids) != len(V2_RULE_IDS)
        or set(actual_ids) != set(V2_RULE_IDS)
    ):
        raise ValueError(
            "V2 requires exactly R01–R06, "
            "with no duplicates."
        )

    return sorted(
        rules,
        key=lambda rule: rule.rule_id,
    )


# ============================================================
# Candidate grouping
# ============================================================

def group_candidates_by_rule(
    candidates: list[V2VerifiedCandidate],
) -> dict[str, list[V2VerifiedCandidate]]:
    """
    Group all verified candidates by rule.

    Preserve:
    - APPLICABLE
    - AMBIGUOUS
    - NOT_APPLICABLE
    - evidence-invalid candidates

    Nothing is discarded at this stage.
    """

    grouped = {
        rule_id: []
        for rule_id in V2_RULE_IDS
    }

    for candidate in candidates:

        rule_id = candidate.candidate.rule_id

        if rule_id not in grouped:
            raise ValueError(
                f"Unexpected V2 rule ID: {rule_id}"
            )

        grouped[rule_id].append(candidate)

    return grouped


# ============================================================
# Deterministic pipeline
# ============================================================

def evaluate_extraction_v2(
    *,
    extraction: V2CandidateExtractionResult,
    contract_text: str,
) -> tuple[ReviewResult, dict[str, Any]]:
    """
    Process an already-extracted model response.

    No LLM calls happen here.

    Useful for:
    - Unit tests
    - Offline replay
    - Deterministic regression testing
    """

    verified_candidates = verify_candidates_v2(
        extraction=extraction,
        contract_text=contract_text,
    )

    grouped = group_candidates_by_rule(
        verified_candidates
    )

    findings = []
    evaluations = []

    for rule_id in V2_RULE_IDS:

        evaluator_input = V2RuleEvaluatorInput(
            rule_id=rule_id,
            candidates=grouped[rule_id],
        )

        evaluation = evaluate_rule_v2(
            evaluator_input
        )

        if evaluation.rule_id != rule_id:
            raise ValueError(
                "Evaluator returned the wrong rule ID."
            )

        evaluations.append(evaluation)

        findings.append(
            Finding(
                rule_id=evaluation.rule_id,
                status=evaluation.status,
                requires_human_review=(
                    evaluation.requires_human_review
                ),
                evidence=evaluation.evidence,
                reason=evaluation.reason,
            )
        )

    result = ReviewResult(
        findings=findings
    )

    actual_ids = [
        finding.rule_id
        for finding in result.findings
    ]

    if (
        len(actual_ids) != 6
        or set(actual_ids) != set(V2_RULE_IDS)
    ):
        raise ValueError(
            "V2 must produce exactly one finding "
            "for each of R01–R06."
        )

    metadata = {
        "version": "v2",
        "candidate_count": len(
            extraction.candidates
        ),
        "verified_candidate_count": sum(
            candidate.evidence_valid
            for candidate in verified_candidates
        ),
        "invalid_candidate_count": sum(
            not candidate.evidence_valid
            for candidate in verified_candidates
        ),
        "candidate_extraction": (
            extraction.model_dump(mode="json")
        ),
        "candidate_verification": [
            candidate.model_dump(mode="json")
            for candidate in verified_candidates
        ],
        "rule_evaluations": [
            evaluation.model_dump(mode="json")
            for evaluation in evaluations
        ],
    }

    return result, metadata


# ============================================================
# LLM extraction pipeline
# ============================================================

def _review_contract_v2_impl(
    *,
    audit_run_id: str,
    contract_text: str,
    contract_source: str,
) -> tuple[ReviewResult, dict[str, Any]]:
    """
    Complete V2 review.

    Makes exactly one batched LLM extraction request
    for the entire contract.

    The LLM does not generate final classifications.
    """

    if not contract_text.strip():
        raise ValueError(
            "Contract text cannot be empty."
        )

    rules = load_v2_rules()

    messages = build_v2_messages(
        contract_text=contract_text,
        rules=rules,
    )

    response_schema = (
        V2CandidateExtractionResult.model_json_schema()
    )

    from contract_review.audit import append_event
    import time

    append_event({
        "event": "llm_call_started",
        "run_id": audit_run_id,
        "version": "v2",
        "contract_source": contract_source,
        "messages": messages,
        "response_schema": response_schema,
        "max_tokens": V2_MAX_TOKENS,
    })

    started = time.perf_counter()

    try:
        llm_response = call_llm(
            messages=messages,
            response_schema=response_schema,
            max_tokens_override=V2_MAX_TOKENS,
        )
    except Exception as exc:
        append_event({
            "event": "llm_call_failed",
            "run_id": audit_run_id,
            "version": "v2",
            "contract_source": contract_source,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "latency_ms": round(
                (time.perf_counter() - started) * 1000, 2
            ),
        })
        raise

    append_event({
        "event": "llm_call_completed",
        "run_id": audit_run_id,
        "version": "v2",
        "contract_source": contract_source,
        "model": llm_response.get("model"),
        "request_id": llm_response.get("request_id"),
        "raw_response": llm_response.get("content"),
        "finish_reason": llm_response.get("finish_reason"),
        "generation_settings": llm_response.get(
            "generation_settings"
        ),
        "usage": {
            "prompt_tokens": llm_response.get("prompt_tokens"),
            "completion_tokens": llm_response.get(
                "completion_tokens"
            ),
            "total_tokens": llm_response.get("total_tokens"),
        },
        "latency_ms": llm_response.get("latency_ms"),
    })

    raw_content = llm_response.get("content")

    finish_reason = llm_response.get(
        "finish_reason"
    )

    if finish_reason != "stop":
        raise ValueError(
            "V2 extraction did not complete normally. "
            f"finish_reason={finish_reason}"
        )

    if not raw_content:
        raise ValueError(
            "V2 extraction returned empty content."
        )

    # Schema validation.
    extraction = (
        V2CandidateExtractionResult.model_validate_json(
            raw_content
        )
    )

    # Exact evidence verification and six deterministic
    # evaluations.
    result, metadata = evaluate_extraction_v2(
        extraction=extraction,
        contract_text=contract_text,
    )

    metadata.update({
        "contract_source": contract_source,
        "model": llm_response.get("model"),
        "request_id": llm_response.get("request_id"),
        "finish_reason": finish_reason,
        "generation_settings": llm_response.get(
            "generation_settings"
        ),
        "usage": {
            "prompt_tokens": llm_response.get(
                "prompt_tokens"
            ),
            "completion_tokens": llm_response.get(
                "completion_tokens"
            ),
            "total_tokens": llm_response.get(
                "total_tokens"
            ),
        },
        "latency_ms": llm_response.get(
            "latency_ms"
        ),
    })

    return result, metadata


def review_contract_v2(
    *,
    contract_text: str,
    contract_source: str,
) -> tuple[ReviewResult, dict[str, Any]]:
    """Run V2 review with correlated audit records."""

    import time
    from uuid import uuid4
    from contract_review.audit import append_event

    run_id = uuid4().hex
    started = time.perf_counter()

    try:
        result, metadata = _review_contract_v2_impl(
            contract_text=contract_text,
            contract_source=contract_source,
            audit_run_id=run_id,
        )

        for finding in result.findings:
            append_event({
                "event": "finding",
                "run_id": run_id,
                "version": "v2",
                "contract_source": contract_source,
                "rule_id": finding.rule_id,
                "status": finding.status,
                "requires_human_review": (
                    finding.requires_human_review
                ),
                "evidence": finding.evidence,
                "reason": finding.reason,
            })

        append_event({
            "event": "review_completed",
            "run_id": run_id,
            "version": "v2",
            "contract_source": contract_source,
            "finding_count": len(result.findings),
            "latency_ms": round(
                (time.perf_counter() - started) * 1000, 2
            ),
            "usage": metadata.get("usage"),
        })

        return result, metadata

    except Exception as exc:
        append_event({
            "event": "review_failed",
            "run_id": run_id,
            "version": "v2",
            "contract_source": contract_source,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "latency_ms": round(
                (time.perf_counter() - started) * 1000, 2
            ),
        })
        raise
