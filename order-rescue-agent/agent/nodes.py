from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from .events import EventType, execution_event, lifecycle_events
from .policy import evaluate_contact_policy, evaluate_recovery_policy
from .reasoning import Reasoner, mock_reasoner
from .schemas import (
    Action,
    Assessment,
    BuyerIntent,
    CaseStatus,
    Confidence,
    Evidence,
    FinalRecommendation,
    Hypothesis,
    InformationRequest,
    PolicyDecision,
)

logger = logging.getLogger("order_rescue.agent")


def build_evidence(state: dict[str, Any]) -> dict[str, Any]:
    context = state["delivery_context"]
    stamp = datetime.now(UTC).isoformat()
    incoming = [
        Evidence(
            evidence_id=f"{state['case_id']}:delivery-status",
            kind="delivery_status",
            value=context.delivery_status,
            provenance="synthetic_delivery_event",
            timestamp=stamp,
        ),
        Evidence(
            evidence_id=f"{state['case_id']}:courier-note",
            kind="courier_note",
            value=context.courier_note,
            provenance="synthetic_courier_note",
            timestamp=stamp,
        ),
    ]
    if state.get("buyer_reply"):
        buyer_evidence = next(
            (item for item in state.get("evidence", []) if item.provenance == "simulated_buyer_reply"),
            None,
        )
        if buyer_evidence:
            incoming.append(buyer_evidence)
    logger.info("[%s] Evidence pack built with %d normalized items.", state["case_id"], len(incoming))
    return {"evidence": incoming, "events": lifecycle_events(state, "build_evidence")}


def assess_case(state: dict[str, Any], reasoner: Reasoner | None = None) -> dict[str, Any]:
    assessment = (reasoner or mock_reasoner).assess(state["delivery_context"], state.get("evidence", []))
    logger.info(
        "[%s] Assessment: %s (%s), missing=%s",
        state["case_id"], assessment.hypothesis.value, assessment.confidence.value, assessment.missing_information,
    )
    events = [execution_event(state, "assess_case", EventType.NODE_STARTED)]
    events.append(execution_event(
        state,
        "assess_case",
        EventType.ASSESSMENT_COMPLETED,
        {
            "hypothesis": assessment.hypothesis.value,
            "confidence": assessment.confidence.value,
            "missing_information": assessment.missing_information,
            "evidence_refs": assessment.evidence_refs,
            "summary": assessment.summary,
        },
    ))
    events.append(execution_event(state, "assess_case", EventType.NODE_COMPLETED))
    return {"assessment": assessment, "missing_information": assessment.missing_information, "events": events}


def plan_information(state: dict[str, Any]) -> dict[str, Any]:
    assessment: Assessment = state["assessment"]
    can_change_action = "buyer_intent" in assessment.missing_information
    can_ask = (
        can_change_action
        and state.get("questions_asked", 0) < 1
        and assessment.hypothesis not in {Hypothesis.SERVICE_DISRUPTION, Hypothesis.UNSUPPORTED_REFUSAL}
    )
    return {"should_ask_buyer": can_ask, "case_status": CaseStatus.RUNNING, "events": lifecycle_events(state, "plan_information")}


def contact_policy_gate(state: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_contact_policy(
        state["delivery_context"], questions_asked=state.get("questions_asked", 0), question_limit=1
    )
    logger.info("[%s] Contact policy: %s", state["case_id"], result.decision.value)
    events = [execution_event(state, "contact_policy_gate", EventType.NODE_STARTED)]
    events.append(execution_event(
        state,
        "contact_policy_gate",
        EventType.POLICY_EVALUATED,
        {"stage": "contact", **result.model_dump(mode="json")},
    ))
    events.append(execution_event(state, "contact_policy_gate", EventType.NODE_COMPLETED))
    return {"contact_policy_result": result, "events": events}


def generate_question(state: dict[str, Any]) -> dict[str, Any]:
    request = InformationRequest(
        question="Would you still like us to attempt delivery?",
        purpose="Confirm buyer intent because it may change the recovery recommendation.",
    )
    events = [execution_event(state, "generate_question", EventType.NODE_STARTED)]
    events.append(execution_event(
        state,
        "generate_question",
        EventType.INFORMATION_REQUESTED,
        {"question": request.question, "purpose": request.purpose, "simulated": True},
    ))
    events.append(execution_event(
        state,
        "generate_question",
        EventType.STATE_TRANSITION,
        {"from": CaseStatus.RUNNING.value, "to": CaseStatus.WAITING_FOR_BUYER.value},
    ))
    events.append(execution_event(state, "generate_question", EventType.NODE_COMPLETED))
    return {
        "information_request": request,
        "proposed_action": Action.CLARIFY,
        "questions_asked": state.get("questions_asked", 0) + 1,
        "case_status": CaseStatus.WAITING_FOR_BUYER,
        "events": events,
    }


def wait_for_buyer(state: dict[str, Any]) -> dict[str, Any]:
    response = interrupt({
        "case_id": state["case_id"],
        "question": state["information_request"].question,
        "simulated": True,
    })
    reply = response.get("text", "") if isinstance(response, dict) else str(response)
    return {"buyer_reply": reply, "events": lifecycle_events(state, "wait_for_buyer")}


def _classify_buyer_intent(reply: str) -> BuyerIntent:
    normalized = re.sub(r"\s+", " ", reply.strip().lower())
    negated_want = re.compile(
        r"\b(?:i\s+)?(?:don't|do not|dont|no longer|never)\s+(?:want|need)"
        r"(?:\s+(?:the\s+)?(?:delivery|order|it|this))?\b"
    )
    positive_text = negated_want.sub(" ", normalized)
    wants_delivery = any(phrase in positive_text for phrase in (
        "still want", "want delivery", "please deliver", "i want it", "yes, deliver", "mình vẫn muốn", "vẫn muốn nhận", "hãy giao",
    ))
    declines_delivery = bool(negated_want.search(normalized)) or any(phrase in normalized for phrase in (
        "cancel", "no longer need", "không muốn nhận", "không cần nữa", "hủy đơn",
    ))
    if wants_delivery and not declines_delivery:
        return BuyerIntent.WANTS_DELIVERY
    if declines_delivery and not wants_delivery:
        return BuyerIntent.DOES_NOT_WANT_DELIVERY
    return BuyerIntent.UNKNOWN


def parse_buyer_reply(state: dict[str, Any]) -> dict[str, Any]:
    reply = (state.get("buyer_reply") or "").strip()
    intent = _classify_buyer_intent(reply)
    context = state["delivery_context"].model_copy(update={"buyer_intent": intent})
    evidence = Evidence(
        evidence_id=f"{state['case_id']}:buyer-reply:{state.get('questions_asked', 1)}",
        kind="buyer_intent",
        value=intent.value,
        provenance="simulated_buyer_reply",
        timestamp=datetime.now(UTC).isoformat(),
        raw_text=reply,
    )
    resumed_state = {**state, "iteration": state.get("iteration", 1) + 1}
    events = [execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_STARTED)]
    events.append(execution_event(
        resumed_state,
        "parse_buyer_reply",
        EventType.BUYER_REPLY_RECEIVED,
        {"intent": intent.value, "evidence_ref": evidence.evidence_id, "raw_reply": reply},
    ))
    events.append(execution_event(
        resumed_state,
        "parse_buyer_reply",
        EventType.STATE_TRANSITION,
        {"from": CaseStatus.WAITING_FOR_BUYER.value, "to": CaseStatus.RUNNING.value},
    ))
    events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_COMPLETED))
    logger.info("[%s] Simulated buyer reply parsed as %s.", state["case_id"], intent.value)
    return {
        "delivery_context": context,
        "evidence": [evidence],
        "iteration": resumed_state["iteration"],
        "case_status": CaseStatus.RUNNING,
        "events": events,
    }


def propose_recovery(state: dict[str, Any]) -> dict[str, Any]:
    assessment: Assessment = state["assessment"]
    contact_result = state.get("contact_policy_result")
    context = state["delivery_context"]
    if contact_result and contact_result.decision is not PolicyDecision.PERMITTED:
        action = Action.ESCALATE_REVIEW
    elif assessment.hypothesis is Hypothesis.SERVICE_DISRUPTION:
        action = Action.HOLD_DISRUPTION
    elif assessment.hypothesis is Hypothesis.UNSUPPORTED_REFUSAL:
        action = Action.ESCALATE_REVIEW
    elif context.buyer_intent is BuyerIntent.WANTS_DELIVERY and not assessment.missing_information:
        action = Action.STANDARD_REATTEMPT
    elif context.buyer_intent is BuyerIntent.DOES_NOT_WANT_DELIVERY:
        action = Action.NO_ACTION
    elif assessment.missing_information and state.get("questions_asked", 0) >= 1:
        action = Action.ESCALATE_REVIEW
    elif assessment.missing_information:
        action = Action.CLARIFY
    else:
        action = Action.NO_ACTION
    logger.info("[%s] Candidate action: %s.", state["case_id"], action.value)
    return {"proposed_action": action, "events": lifecycle_events(state, "propose_recovery")}


def recovery_policy_gate(state: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_recovery_policy(state["proposed_action"], state["delivery_context"], state["assessment"])
    logger.info("[%s] Recovery policy: %s (%s).", state["case_id"], result.decision.value, result.triggering_rule_ids)
    events = [execution_event(state, "recovery_policy_gate", EventType.NODE_STARTED)]
    events.append(execution_event(
        state,
        "recovery_policy_gate",
        EventType.POLICY_EVALUATED,
        {"stage": "recovery", **result.model_dump(mode="json")},
    ))
    events.append(execution_event(state, "recovery_policy_gate", EventType.NODE_COMPLETED))
    return {"recovery_policy_result": result, "events": events}


def finalize(state: dict[str, Any]) -> dict[str, Any]:
    policy = state.get("recovery_policy_result")
    if policy is None:
        raise ValueError("Cannot publish a recommendation before recovery policy evaluation.")
    try:
        candidate = Action(state["proposed_action"])
    except ValueError:
        candidate = None
    if policy.decision is PolicyDecision.PERMITTED and candidate is None:
        raise ValueError("Policy cannot permit an action outside the registered vocabulary.")
    action = candidate if policy.decision is PolicyDecision.PERMITTED else Action.ESCALATE_REVIEW
    if action is Action.STANDARD_REATTEMPT:
        rationale = "Buyer confirmed delivery intent and the illustrative demo policy permits recommending a standard reattempt. No courier action was executed."
    elif policy.decision is PolicyDecision.ESCALATE:
        rationale = "The evidence or policy requires human review; no automatic recovery action was taken."
    elif policy.decision is PolicyDecision.BLOCKED:
        rationale = "The candidate recovery action is blocked by the illustrative demo policy; refer the case for human review."
    else:
        rationale = f"The policy permits the recommendation {action.value}; no logistics action was executed."

    recommendation = FinalRecommendation(
        action=action,
        policy_decision=policy.decision,
        policy_version=policy.policy_version,
        rationale=rationale,
        executed=False,
        side_effects=[],
    )
    status = (
        CaseStatus.COMPLETED if policy.decision is PolicyDecision.PERMITTED
        else CaseStatus.ESCALATED if policy.decision is PolicyDecision.ESCALATE
        else CaseStatus.BLOCKED
    )
    events = [execution_event(state, "finalize", EventType.NODE_STARTED)]
    events.append(execution_event(
        state,
        "finalize",
        EventType.RECOMMENDATION_PUBLISHED,
        {"action": action.value, "policy_decision": policy.decision.value, "executed": False},
    ))
    events.append(execution_event(state, "finalize", EventType.STATE_TRANSITION, {"to": status.value}))
    events.append(execution_event(state, "finalize", EventType.NODE_COMPLETED))
    logger.info("[%s] Published recommendation: %s (%s).", state["case_id"], action.value, policy.decision.value)
    return {"final_recommendation": recommendation, "case_status": status, "events": events}
