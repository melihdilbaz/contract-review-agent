from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FindingStatus = Literal[
    "COMPLIANT",
    "NON_COMPLIANT",
    "NOT_FOUND",
]


class Rule(BaseModel):
    rule_id: str
    policy: str


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    status: FindingStatus
    requires_human_review: bool
    evidence: list[str]
    reason: str


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
