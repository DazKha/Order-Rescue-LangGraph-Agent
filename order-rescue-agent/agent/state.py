from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, TypedDict

from .schemas import (
    Assessment,
    AgentDecision,
    BiCaseInput,
    CaseEvent,
    CaseStatus,
    DeliveryContext,
    Evidence,
    ExecutionEvent,
    FinalRecommendation,
    InformationRequest,
    PolicyResult,
)


def merge_evidence(left: list[Evidence] | None, right: Iterable[Evidence] | None) -> list[Evidence]:
    merged = {item.evidence_id: item for item in (left or [])}
    for item in right or []:
        merged[item.evidence_id] = item
    return list(merged.values())


def merge_events(left: list[ExecutionEvent] | None, right: Iterable[ExecutionEvent] | None) -> list[ExecutionEvent]:
    merged = {item.event_id: item for item in (left or [])}
    for item in right or []:
        merged.setdefault(item.event_id, item)
    return list(merged.values())


class AgentState(TypedDict, total=False):
    case_id: str
    trigger_event: str
    case_input: BiCaseInput
    case_event: CaseEvent | None
    input_issues: list[str]
    eligibility: str
    delivery_context: DeliveryContext
    evidence: Annotated[list[Evidence], merge_evidence]
    assessment: Assessment | None
    llm_decision: AgentDecision | None
    missing_information: list[str]
    information_request: InformationRequest | None
    buyer_reply: str | None
    questions_asked: int
    proposed_action: str | None
    contact_policy_result: PolicyResult | None
    recovery_policy_result: PolicyResult | None
    final_recommendation: FinalRecommendation | None
    case_status: CaseStatus
    iteration: int
    should_ask_buyer: bool
    should_wait_event: bool
    event_target: str
    events: Annotated[list[ExecutionEvent], merge_events]
