from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


MISSING_INFORMATION_VALUES = frozenset({
    "buyer_intent",
    "address_landmark",
    "refusal_evidence",
    "failure_context",
})


class Action(StrEnum):
    CLARIFY = "CLARIFY"
    STANDARD_REATTEMPT = "STANDARD_REATTEMPT"
    HOLD_DISRUPTION = "HOLD_DISRUPTION"
    ESCALATE_REVIEW = "ESCALATE_REVIEW"
    NO_ACTION = "NO_ACTION"


class CaseStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_FOR_BUYER = "WAITING_FOR_BUYER"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Hypothesis(StrEnum):
    TEMP_AVAILABILITY_CONFLICT = "TEMP_AVAILABILITY_CONFLICT"
    BUYER_UNREACHABLE = "BUYER_UNREACHABLE"
    UNCLEAR_ADDRESS = "UNCLEAR_ADDRESS"
    SERVICE_DISRUPTION = "SERVICE_DISRUPTION"
    UNSUPPORTED_REFUSAL = "UNSUPPORTED_REFUSAL"
    UNKNOWN = "UNKNOWN"


class BuyerIntent(StrEnum):
    UNKNOWN = "UNKNOWN"
    WANTS_DELIVERY = "WANTS_DELIVERY"
    DOES_NOT_WANT_DELIVERY = "DOES_NOT_WANT_DELIVERY"


class ReturnState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"


class PolicyDecision(StrEnum):
    PERMITTED = "PERMITTED"
    BLOCKED = "BLOCKED"
    ESCALATE = "ESCALATE"


class RuleResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class DomainModel(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class DeliveryContext(DomainModel):
    delivery_status: str
    courier_note: str = ""
    attempt_count: int | None = Field(default=None, ge=0)
    attempt_limit: int | None = Field(default=None, ge=0)
    return_state: ReturnState | None = ReturnState.NOT_STARTED
    contact_eligible: bool | None = True
    unsupported_refusal: bool = False
    buyer_intent: BuyerIntent = BuyerIntent.UNKNOWN


class Evidence(DomainModel):
    evidence_id: str
    kind: str
    value: str
    provenance: str
    timestamp: str
    raw_text: str | None = None


class Assessment(DomainModel):
    hypothesis: Hypothesis
    confidence: Confidence
    missing_information: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    summary: str

    @field_validator("missing_information")
    @classmethod
    def validate_missing_information(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - MISSING_INFORMATION_VALUES)
        if unknown:
            raise ValueError("missing_information contains unregistered values")
        return values


class InformationRequest(DomainModel):
    question: str
    purpose: str
    simulated: bool = True


class PolicyRule(DomainModel):
    rule_id: str
    result: RuleResult
    reason: str


class PolicyResult(DomainModel):
    decision: PolicyDecision
    policy_version: str = "DEMO-POLICY-0.1"
    rules: list[PolicyRule]
    triggering_rule_ids: list[str] = Field(default_factory=list)


class FinalRecommendation(DomainModel):
    action: Action
    policy_decision: PolicyDecision
    policy_version: str
    rationale: str
    executed: bool = False
    side_effects: list[str] = Field(default_factory=list)


class ExecutionEvent(DomainModel):
    event_id: str
    case_id: str
    iteration: int
    node_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)
