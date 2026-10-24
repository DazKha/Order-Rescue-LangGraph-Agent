from __future__ import annotations

import logging
import json
import re
from datetime import UTC, datetime
from typing import Any
from pydantic import ValidationError

from langgraph.types import interrupt

from .bi_adapter import validate_case_input
from .events import EventType, execution_event, lifecycle_events
from .policy import evaluate_bi_eligibility, evaluate_contact_policy, evaluate_recovery_policy
from .reasoning import DecisionReasoner
from .schemas import (
    Action,
    AgentDecision,
    Assessment,
    BiCaseInput,
    BuyerIntent,
    CaseEvent,
    CaseStatus,
    Confidence,
    DecisionRoute,
    DecisionStage,
    DecisionTarget,
    DeliveryContext,
    Evidence,
    Eligibility,
    FinalRecommendation,
    Hypothesis,
    InformationRequest,
    PolicyDecision,
    PolicyResult,
    PolicyRule,
    RuleResult,
    EventType as BiEventType,
)

logger = logging.getLogger("order_rescue.agent")


def validate_input(state: dict[str, Any]) -> dict[str, Any]:
    source = state["case_input"]
    raw = source.model_dump(mode="json") if isinstance(source, BiCaseInput) else source
    result = validate_case_input(raw)
    case = result.case or source
    context_source = state.get("delivery_context")
    context = (
        context_source if isinstance(context_source, DeliveryContext)
        else DeliveryContext.model_validate(context_source) if context_source is not None
        else None
    )
    issues = list(result.issues)
    preflight: tuple[Action, PolicyDecision, str, str] | None = None
    raw_event = state.get("case_event")
    event: CaseEvent | None = None
    if raw_event is not None:
        try:
            event = raw_event if isinstance(raw_event, CaseEvent) else CaseEvent.model_validate(raw_event)
        except ValidationError:
            issues.append("case_event")
        else:
            if event.case_id != state["case_id"]:
                issues.append("case_event.case_id")

    extra = case.extra_context if isinstance(case, BiCaseInput) else {}
    note = (case.courier_note or "") if isinstance(case, BiCaseInput) else ""
    if issues and result.valid:
        preflight = (
            Action.ESCALATE_REVIEW,
            PolicyDecision.BLOCKED, "R16", "The resumed event is invalid for this case.",
        )
    elif result.valid and extra.get("pii_detected") is True:
        issues = ["pii_detected"]
        preflight = (
            Action.ESCALATE_REVIEW,
            PolicyDecision.BLOCKED, "R15", "PII marker requires dropping this record before reasoning.",
        )
    elif result.valid and re.search(r"ignore all (?:previous )?rules|bỏ qua mọi quy tắc", note, re.I):
        issues = ["untrusted_instruction_in_case_data"]
        preflight = (
            Action.ESCALATE_REVIEW,
            PolicyDecision.ESCALATED, "R19", "Instruction-like text is case data and is routed to human review.",
        )
    elif result.valid and (extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"}):
        issues = ["duplicate_or_stale_event"]
        preflight = (
            Action.NO_ACTION,
            PolicyDecision.BLOCKED, "R20", "Duplicate or stale input cannot create a new decision.",
        )
    elif not result.valid:
        preflight = (
            Action.ESCALATE_REVIEW,
            PolicyDecision.BLOCKED, "R16", "Required input is missing or outside the registered BI vocabulary.",
        )
    elif isinstance(case, BiCaseInput):
        eligibility = evaluate_bi_eligibility(case)
        if eligibility is not Eligibility.ELIGIBLE:
            rule_id = (
                "R01" if case.return_state in {"started", "completed"} else
                "R04" if case.attempts_remaining == 0 else
                "R02" if eligibility is Eligibility.UNKNOWN else "R03"
            )
            preflight = (
                Action.ESCALATE_REVIEW,
                PolicyDecision.ESCALATED if eligibility is Eligibility.UNKNOWN else PolicyDecision.BLOCKED,
                rule_id, "Eligibility pre-check requires Ops review before AI assessment.",
            )

    events = [execution_event(state, "validate_input", EventType.NODE_STARTED)]
    update: dict[str, Any] = {"case_input": case, "input_issues": issues}
    if event is not None:
        update["case_event"] = event
    if context is not None:
        update["delivery_context"] = context
    if isinstance(case, BiCaseInput) and result.valid:
        update["eligibility"] = (
            "UNKNOWN" if extra.get("pii_detected") else
            "INELIGIBLE" if extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"} else
            evaluate_bi_eligibility(case).value
        )
    elif isinstance(case, BiCaseInput):
        update["eligibility"] = "UNKNOWN"
    if preflight:
        action, decision, rule_id, reason = preflight
        policy = PolicyResult(
            decision=decision,
            policy_version=(case.policy_version if isinstance(case, BiCaseInput) and case.policy_version else "DEMO-POLICY-0.1"),
            rules=[PolicyRule(rule_id=rule_id, result=RuleResult.FAIL, reason=reason)],
            triggering_rule_ids=[rule_id],
        )
        update.update({
            "assessment": None,
            "missing_information": issues,
            "proposed_action": action,
            "recovery_policy_result": policy,
        })
        events.append(execution_event(state, "validate_input", EventType.POLICY_EVALUATED, {
            "stage": "input", **policy.model_dump(mode="json"),
        }))
    events.append(execution_event(state, "validate_input", EventType.NODE_COMPLETED))
    update["events"] = events
    return update


def build_evidence(state: dict[str, Any]) -> dict[str, Any]:
    context = state["delivery_context"]
    case: BiCaseInput | None = state.get("case_input")
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
    if case is not None:
        # Preserve BI input as evidence without ever adding expected labels or
        # an unrevealed later event to the reasoner's prompt.
        for field in (
            "raw_reason", "service_type", "route_type", "area_type", "payment_type",
            "attempt_current", "attempts_remaining", "attempt_history", "contact_evidence",
            "return_state", "decision_deadline", "address_issue", "disruption_signal", "actor_role",
        ):
            value = getattr(case, field)
            if value not in (None, "", [], {}):
                incoming.append(Evidence(
                    evidence_id=f"{state['case_id']}:input:{field}",
                    kind=field,
                    value=json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value),
                    provenance="synthetic_bi_case_input",
                    timestamp=stamp,
                ))
    raw_event = state.get("case_event")
    if raw_event is not None:
        event = raw_event if isinstance(raw_event, CaseEvent) else CaseEvent.model_validate(raw_event)
        prior_request = state.get("information_request")
        if prior_request is not None and state.get("event_target") == "BUYER":
            incoming.append(Evidence(
                evidence_id=f"{state['case_id']}:buyer-question:{state.get('questions_asked', 1)}",
                kind="buyer_question",
                value=prior_request.question,
                provenance="simulated_agent_question",
                timestamp=stamp,
                raw_text=prior_request.question,
            ))
        incoming.append(Evidence(
            evidence_id=f"{state['case_id']}:event:{event.event_type.value}:{state.get('iteration', 1)}",
            kind=event.event_type.value.lower(),
            value=event.event_text or event.event_type.value,
            provenance="simulated_bi_event",
            timestamp=stamp,
            raw_text=event.event_text,
        ))
    elif state.get("buyer_reply") is not None:
        reply = state["buyer_reply"]
        incoming.append(Evidence(
            evidence_id=f"{state['case_id']}:buyer-reply-raw:{state.get('questions_asked', 1)}",
            kind="raw_buyer_reply",
            value=reply or "NO_REPLY",
            provenance="simulated_buyer_reply",
            timestamp=stamp,
            raw_text=reply,
        ))
    logger.info("[%s] Evidence pack built with %d normalized items.", state["case_id"], len(incoming))
    return {"evidence": incoming, "events": lifecycle_events(state, "build_evidence")}


def assess_case(state: dict[str, Any], reasoner: DecisionReasoner | None = None) -> dict[str, Any]:
    if reasoner is None:
        raise ValueError("A configured LLM decision provider is required for eligible cases.")
    event = state.get("case_event")
    if event is not None and not isinstance(event, CaseEvent):
        event = CaseEvent.model_validate(event)
    stage = DecisionStage.AFTER_EVENT if event is not None else DecisionStage.INITIAL
    decision = reasoner.decide(
        state["delivery_context"], state.get("evidence", []),
        stage=stage, case_input=state.get("case_input"), case_event=event,
    )
    if not isinstance(decision, AgentDecision):
        decision = AgentDecision.model_validate(decision)
    if decision.stage is not stage:
        raise ValueError("Decision stage did not match the graph stage.")
    known_ids = {item.evidence_id for item in state.get("evidence", [])}
    if not set(decision.evidence_refs + decision.assessment.evidence_refs) <= known_ids:
        raise ValueError("Decision referenced evidence outside the current evidence pack.")
    assessment = decision.assessment
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
    update = {
        "assessment": assessment, "missing_information": assessment.missing_information,
        "llm_decision": decision, "events": events,
    }
    if stage is DecisionStage.AFTER_EVENT:
        update["delivery_context"] = state["delivery_context"].model_copy(
            update={"buyer_intent": decision.buyer_intent or BuyerIntent.UNKNOWN}
        )
        update["parsed_facts"] = decision.parsed_facts
    return update


def plan_information(state: dict[str, Any]) -> dict[str, Any]:
    assessment: Assessment = state["assessment"]
    case: BiCaseInput | None = state.get("case_input")
    askable_fields = {
        "buyer_intent", "availability", "return_date", "working_day_availability",
        "third_party_receipt_ok", "pickup_point_at_gate", "landmark",
        "house_number_or_landmark", "block_floor_unit", "new_address_authorized",
        "next_route_date", "ability_to_pay", "orderer_intent", "recipient_awareness",
        "alternate_contact_channel", "valid_contact", "sender_decision",
    }
    decision: AgentDecision | None = state.get("llm_decision")
    has_actionable_llm_question = bool(
        decision
        and decision.route is DecisionRoute.ASK
        and decision.target is DecisionTarget.BUYER
        and decision.information_request is not None
        and assessment.missing_information
    )
    can_change_action = bool(set(assessment.missing_information).intersection(askable_fields)) or has_actionable_llm_question
    human_review_hypotheses = {
        Hypothesis.REFUSAL_UNSUPPORTED, Hypothesis.REFUSAL_CONFIRMED,
        Hypothesis.LIFECYCLE_CLOSED,
        Hypothesis.OFF_SYSTEM_HOLD_SUSPECTED, Hypothesis.PARCEL_DAMAGE,
        Hypothesis.SECURITY_INPUT_ANOMALY, Hypothesis.DATA_QUALITY_INVALID,
        Hypothesis.RECORD_CONFLICT, Hypothesis.OUT_OF_SCOPE_REQUEST,
    }
    needs_operational_event = bool(
        case and case.disruption_signal.get("flag") and case.disruption_signal.get("verified")
        and case.disruption_signal.get("type") != "PEAK_CAPACITY"
    )
    if needs_operational_event and case:
        signal_scope = case.disruption_signal.get("scope") or ""
        route = case.extra_context.get("parcel_route")
        needs_operational_event = not state.get("case_event") or state["case_event"].event_type.value != "DISRUPTION_RESOLVED"
        needs_operational_event = needs_operational_event and (not route or route in signal_scope or signal_scope.endswith("ALL"))
    target = "BUYER"
    seller_updated = bool(state.get("case_event") and state["case_event"].event_type.value == "SELLER_UPDATE")
    seller_replied = bool(state.get("case_event") and state["case_event"].event_type.value == "SELLER_REPLY")
    if needs_operational_event:
        target = "OPS"
    if case and not seller_replied and case.actor_role == "SELLER" and case.extra_context.get("pending_sender_confirmation"):
        target = "SELLER"
        needs_operational_event = True
    elif case and not seller_updated and any(item.get("outcome") == "invalid_number" for item in case.contact_evidence):
        target = "SELLER"
        needs_operational_event = True
    can_ask = (
        can_change_action
        and state.get("questions_asked", 0) < 1
        and assessment.hypothesis not in human_review_hypotheses
        and not needs_operational_event
        and (not case or state.get("eligibility", "ELIGIBLE") == "ELIGIBLE"
             or assessment.missing_information == ["buyer_intent"]
             or (assessment.hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and "buyer_intent" in assessment.missing_information))
        and not (case and case.extra_context.get("holiday_in_window") and not case.decision_deadline)
    )
    should_wait = can_ask or needs_operational_event
    if decision is not None:
        if decision.route is DecisionRoute.PROPOSE_RECOVERY:
            can_ask = False
            should_wait = False
        elif decision.target is None:
            can_ask = False
            should_wait = False
        else:
            target = decision.target.value
            buyer_question_eligible = can_ask
            can_ask = decision.route is DecisionRoute.ASK and target == "BUYER" and buyer_question_eligible
            should_wait = can_ask
    return {
        "should_ask_buyer": can_ask,
        "should_wait_event": should_wait,
        "event_target": target,
        "case_status": CaseStatus.RUNNING,
        "events": lifecycle_events(state, "plan_information"),
    }


def contact_policy_gate(state: dict[str, Any]) -> dict[str, Any]:
    case: BiCaseInput | None = state.get("case_input")
    if case is not None:
        from .policy import evaluate_bi_contact_policy
        result = evaluate_bi_contact_policy(
            case, questions_asked=state.get("questions_asked", 0), question_limit=1,
            target=state.get("event_target", "BUYER"),
            contact_verified=bool(state.get("case_event") and state["case_event"].event_type.value == "SELLER_UPDATE"),
        )
    else:
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
    target = state.get("event_target", "BUYER")
    case: BiCaseInput | None = state.get("case_input")
    decision: AgentDecision | None = state.get("llm_decision")
    if decision is not None and decision.route is DecisionRoute.ASK and decision.information_request is not None:
        question = decision.information_request.question
        purpose = decision.information_request.purpose
    elif target == "SELLER":
        if case and case.extra_context.get("pending_sender_confirmation"):
            question = "Người gửi có muốn giao lại đơn này không?"
            purpose = "Confirm the sender's decision under the simulated seller-authority policy."
        else:
            question = "Please verify the buyer's current contact number through the authorized seller channel."
            purpose = "Buyer contact is invalid; an authorized seller update is needed before any buyer contact."
    elif case and case.disruption_signal.get("flag") and case.disruption_signal.get("verified") and not (
        state.get("case_event") and state["case_event"].event_type.value == "DISRUPTION_RESOLVED"
    ):
        question = "Please confirm when the verified delivery disruption has cleared for this route."
        purpose = "Wait for an operational recovery event before reassessing the delivery case."
    else:
        fields = set(state["assessment"].missing_information)
        if "availability" in fields:
            question = "Bạn còn muốn nhận đơn này không, và khoảng thời gian nào thuận tiện?"
        elif "return_date" in fields:
            question = "Bạn còn muốn nhận đơn này không và khi nào có mặt nhận hàng?"
        elif "landmark" in fields:
            question = "Bạn có thể cho biết mốc nhận diện gần địa chỉ để hỗ trợ tìm đúng điểm giao không?"
        else:
            question = "Bạn còn muốn nhận đơn hàng này không?"
        purpose = "Confirm only the missing information that could change the recovery recommendation."
    request = InformationRequest(
        question=question,
        purpose=purpose,
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
        {"from": CaseStatus.RUNNING.value, "to": (CaseStatus.WAITING_FOR_BUYER if target == "BUYER" else CaseStatus.WAITING_FOR_EVENT).value},
    ))
    events.append(execution_event(state, "generate_question", EventType.NODE_COMPLETED))
    return {
        "information_request": request,
        "questions_asked": state.get("questions_asked", 0) + (1 if target == "BUYER" else 0),
        "case_status": CaseStatus.WAITING_FOR_BUYER if target == "BUYER" else CaseStatus.WAITING_FOR_EVENT,
        "events": events,
    }


def wait_for_buyer(state: dict[str, Any]) -> dict[str, Any]:
    response = interrupt({
        "case_id": state["case_id"],
        "question": state["information_request"].question,
        "target": state.get("event_target", "BUYER"),
        "event_types": [item.value for item in BiEventType],
        "simulated": True,
    })
    if isinstance(response, dict) and response.get("case_event"):
        event = response["case_event"]
        reply = event.get("event_text", "") if isinstance(event, dict) else ""
    else:
        reply = response.get("text", "") if isinstance(response, dict) else str(response)
        event = CaseEvent(
            case_id=state["case_id"],
            event_type=BiEventType.BUYER_REPLY if reply.strip() else BiEventType.NO_REPLY,
            event_text=reply or None,
            reply_received=bool(reply.strip()),
        )
    resumed_state = {**state, "iteration": state.get("iteration", 1) + 1}
    events = [execution_event(resumed_state, "wait_for_buyer", EventType.NODE_STARTED)]
    events.append(execution_event(resumed_state, "wait_for_buyer", EventType.STATE_TRANSITION, {
        "from": state.get("case_status", CaseStatus.WAITING_FOR_BUYER).value,
        "to": CaseStatus.RUNNING.value,
    }))
    events.append(execution_event(resumed_state, "wait_for_buyer", EventType.NODE_COMPLETED))
    return {
        "case_event": event,
        "buyer_reply": reply or "",
        "case_status": CaseStatus.RUNNING,
        "iteration": resumed_state["iteration"],
        "llm_decision": None,
        "proposed_action": None,
        "contact_policy_result": None,
        "recovery_policy_result": None,
        "events": events,
    }


def propose_recovery(state: dict[str, Any]) -> dict[str, Any]:
    assessment: Assessment = state["assessment"]
    contact_result = state.get("contact_policy_result")
    context = state["delivery_context"]
    case: BiCaseInput | None = state.get("case_input")
    decision: AgentDecision | None = state.get("llm_decision")
    if case and case.extra_context.get("duplicate_of"):
        action = Action.NO_ACTION
    elif contact_result and contact_result.decision is not PolicyDecision.PERMITTED:
        action = Action.ESCALATE_REVIEW
    elif (decision is not None and decision.route is DecisionRoute.PROPOSE_RECOVERY
          and decision.proposed_action is Action.CLARIFY):
        action = Action.ESCALATE_REVIEW
    elif (decision is not None and decision.route is DecisionRoute.PROPOSE_RECOVERY
          and decision.proposed_action is not None and not assessment.missing_information):
        action = decision.proposed_action
    elif context.buyer_intent is BuyerIntent.DOES_NOT_WANT_DELIVERY:
        reply_text = state.get("buyer_reply") or (state.get("case_event").event_text if state.get("case_event") else "")
        action = Action.ESCALATE_REVIEW if any(term in reply_text.lower() for term in ("hoàn tiền", "refund", "hủy")) else Action.NO_ACTION
    elif assessment.hypothesis is Hypothesis.SERVICE_DISRUPTION and case and case.disruption_signal.get("verified"):
        action = Action.HOLD_DISRUPTION
    elif assessment.hypothesis in {
        Hypothesis.SERVICE_DISRUPTION, Hypothesis.UNSUPPORTED_REFUSAL, Hypothesis.REFUSAL_CONFIRMED,
        Hypothesis.PARCEL_DAMAGE, Hypothesis.ADDRESS_MISMATCH, Hypothesis.LIFECYCLE_CLOSED,
        Hypothesis.OFF_SYSTEM_HOLD_SUSPECTED, Hypothesis.SECURITY_INPUT_ANOMALY,
        Hypothesis.DATA_QUALITY_INVALID, Hypothesis.RECORD_CONFLICT, Hypothesis.OUT_OF_SCOPE_REQUEST,
    }:
        action = Action.ESCALATE_REVIEW
    elif context.buyer_intent is BuyerIntent.WANTS_DELIVERY and not assessment.missing_information:
        action = Action.STANDARD_REATTEMPT
    elif assessment.missing_information and state.get("questions_asked", 0) >= 1:
        action = Action.ESCALATE_REVIEW
    elif assessment.missing_information:
        action = Action.CLARIFY
    else:
        action = Action.NO_ACTION
    if case and state.get("eligibility", "ELIGIBLE") != "ELIGIBLE" and action not in {Action.NO_ACTION, Action.ESCALATE_REVIEW}:
        action = Action.ESCALATE_REVIEW
    logger.info("[%s] Candidate action: %s.", state["case_id"], action.value)
    return {"proposed_action": action, "events": lifecycle_events(state, "propose_recovery")}


def recovery_policy_gate(state: dict[str, Any]) -> dict[str, Any]:
    case: BiCaseInput | None = state.get("case_input")
    if case is not None:
        from .policy import evaluate_bi_recovery_policy
        intent = state["delivery_context"].buyer_intent
        result = evaluate_bi_recovery_policy(
            state["proposed_action"], case, state["assessment"],
            buyer_intent=intent, event=state.get("case_event"),
        )
    else:
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
    action = (
        candidate if policy.decision is PolicyDecision.PERMITTED
        else Action.NO_ACTION if candidate is Action.NO_ACTION
        else Action.ESCALATE_REVIEW
    )
    if action is Action.NO_ACTION:
        rationale = "No new action was created because the case is invalid, duplicate, or stale."
    elif action is Action.STANDARD_REATTEMPT:
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
