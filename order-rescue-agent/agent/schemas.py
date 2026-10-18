from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Action(StrEnum):
    CLARIFY = "CLARIFY"
    STANDARD_REATTEMPT = "STANDARD_REATTEMPT"
    HOLD_DISRUPTION = "HOLD_DISRUPTION"
    ESCALATE_REVIEW = "ESCALATE_REVIEW"
    NO_ACTION = "NO_ACTION"


class CaseStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_FOR_BUYER = "WAITING_FOR_BUYER"
    WAITING_FOR_EVENT = "WAITING_FOR_EVENT"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DecisionStage(StrEnum):
    INITIAL = "INITIAL"
    AFTER_EVENT = "AFTER_EVENT"


class DecisionRoute(StrEnum):
    ASK = "ASK"
    WAIT_FOR_EVENT = "WAIT_FOR_EVENT"
    PROPOSE_RECOVERY = "PROPOSE_RECOVERY"


class DecisionTarget(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    OPS = "OPS"


class Hypothesis(StrEnum):
    TEMP_AVAILABILITY_CONFLICT = "TEMP_AVAILABILITY_CONFLICT"
    ACCESS_RESTRICTION = "ACCESS_RESTRICTION"
    ADDRESS_LANDMARK_UNCLEAR = "ADDRESS_LANDMARK_UNCLEAR"
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    LEGACY_ADMIN_ADDRESS = "LEGACY_ADMIN_ADDRESS"
    CONTACT_DATA_INVALID = "CONTACT_DATA_INVALID"
    RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE = "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE"
    REFUSAL_UNSUPPORTED = "REFUSAL_UNSUPPORTED"
    REFUSAL_CONFIRMED = "REFUSAL_CONFIRMED"
    BUYER_INTENT_UNCERTAIN = "BUYER_INTENT_UNCERTAIN"
    PAYMENT_OBSTACLE_COD = "PAYMENT_OBSTACLE_COD"
    SERVICE_DISRUPTION = "SERVICE_DISRUPTION"
    CAPACITY_PEAK = "CAPACITY_PEAK"
    RECORD_CONFLICT = "RECORD_CONFLICT"
    LIFECYCLE_CLOSED = "LIFECYCLE_CLOSED"
    PARCEL_DAMAGE = "PARCEL_DAMAGE"
    OUT_OF_SCOPE_REQUEST = "OUT_OF_SCOPE_REQUEST"
    OFF_SYSTEM_HOLD_SUSPECTED = "OFF_SYSTEM_HOLD_SUSPECTED"
    SECURITY_INPUT_ANOMALY = "SECURITY_INPUT_ANOMALY"
    DATA_QUALITY_INVALID = "DATA_QUALITY_INVALID"
    UNKNOWN = "UNKNOWN"

    # Compatibility aliases for the first V0 implementation.
    BUYER_UNREACHABLE = "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE"
    UNCLEAR_ADDRESS = "ADDRESS_LANDMARK_UNCLEAR"
    UNSUPPORTED_REFUSAL = "REFUSAL_UNSUPPORTED"


class BuyerIntent(StrEnum):
    UNKNOWN = "UNKNOWN"
    WANTS = "WANTS"
    DECLINES = "DECLINES"
    CONDITIONAL = "CONDITIONAL"

    WANTS_DELIVERY = "WANTS"
    DOES_NOT_WANT_DELIVERY = "DECLINES"


class ReturnState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


class PolicyDecision(StrEnum):
    PERMITTED = "PERMITTED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"

    ESCALATE = "ESCALATED"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    BUYER_REPLY = "BUYER_REPLY"
    BUYER_REPLY_LATE = "BUYER_REPLY_LATE"
    NO_REPLY = "NO_REPLY"
    TIMEOUT = "TIMEOUT"
    SELLER_REPLY = "SELLER_REPLY"
    SELLER_UPDATE = "SELLER_UPDATE"
    DISRUPTION_RESOLVED = "DISRUPTION_RESOLVED"


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


class BiCaseInput(DomainModel):
    """Observable input columns from the workbook's Cases sheet."""

    case_id: str
    group: str | None = None
    title: str | None = None
    test_type: str | None = None
    failed_at: str | None = None
    assessed_at: str | None = None
    raw_status: str | None = None
    raw_reason: str | None = None
    courier_note: str | None = None
    service_type: str | None = None
    route_type: str | None = None
    area_type: str | None = None
    payment_type: str | None = None
    cod_amount_vnd: int | None = None
    parcel_value_vnd: int | None = None
    attempt_current: int | None = Field(default=None, ge=0)
    attempts_remaining: int | None = Field(default=None, ge=0)
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    contact_evidence: list[dict[str, Any]] = Field(default_factory=list)
    return_state: str | None = None
    return_started_at: str | None = None
    decision_deadline: str | None = None
    address_issue: str | None = None
    disruption_signal: dict[str, Any] = Field(default_factory=dict)
    actor_role: str | None = None
    policy_version: str | None = None
    extra_context: dict[str, Any] = Field(default_factory=dict)


class CaseEvent(DomainModel):
    """One delayed event from the workbook; never part of initial case input."""

    case_id: str
    event_type: EventType
    event_text: str | None = None
    reply_received: bool | None = None
    buyer_intent: BuyerIntent | None = None
    availability: str | None = None


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
        if any(not item.strip() or len(item) > 100 for item in values):
            raise ValueError("missing_information entries must be non-empty labels no longer than 100 characters")
        return values


class InformationRequest(DomainModel):
    question: str
    purpose: str
    simulated: bool = True


class AgentDecision(DomainModel):
    stage: DecisionStage
    assessment: Assessment
    route: DecisionRoute
    target: DecisionTarget | None = None
    information_request: InformationRequest | None = None
    buyer_intent: BuyerIntent | None = None
    parsed_facts: dict[str, str] = Field(default_factory=dict)
    proposed_action: Action | None = None
    rationale: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


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
