from __future__ import annotations

import logging
import json
import re
import inspect
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from .bi_adapter import validate_case_input
from .events import EventType, execution_event, lifecycle_events
from .policy import evaluate_bi_eligibility, evaluate_contact_policy, evaluate_recovery_policy
from .reasoning import DecisionReasoner, Reasoner, mock_reasoner
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
    Evidence,
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
    issues = list(result.issues)
    preflight: tuple[Hypothesis, Action, PolicyDecision, str, str] | None = None

    extra = case.extra_context if isinstance(case, BiCaseInput) else {}
    note = (case.courier_note or "") if isinstance(case, BiCaseInput) else ""
    if result.valid and extra.get("pii_detected") is True:
        issues = ["pii_detected"]
        preflight = (
            Hypothesis.DATA_QUALITY_INVALID, Action.ESCALATE_REVIEW,
            PolicyDecision.BLOCKED, "R15", "PII marker requires dropping this record before reasoning.",
        )
    elif result.valid and re.search(r"ignore all (?:previous )?rules|bỏ qua mọi quy tắc", note, re.I):
        issues = ["untrusted_instruction_in_case_data"]
        preflight = (
            Hypothesis.SECURITY_INPUT_ANOMALY, Action.ESCALATE_REVIEW,
            PolicyDecision.ESCALATED, "R19", "Instruction-like text is case data and is routed to human review.",
        )
    elif result.valid and (extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"}):
        issues = ["duplicate_or_stale_event"]
        preflight = (
            Hypothesis.DATA_QUALITY_INVALID, Action.NO_ACTION,
            PolicyDecision.BLOCKED, "R20", "Duplicate or stale input cannot create a new decision.",
        )
    elif not result.valid:
        preflight = (
            Hypothesis.DATA_QUALITY_INVALID, Action.ESCALATE_REVIEW,
            PolicyDecision.BLOCKED, "R16", "Required input is missing or outside the registered BI vocabulary.",
        )

    events = [execution_event(state, "validate_input", EventType.NODE_STARTED)]
    update: dict[str, Any] = {"case_input": case, "input_issues": issues}
    if isinstance(case, BiCaseInput) and result.valid:
        update["eligibility"] = (
            "UNKNOWN" if extra.get("pii_detected") else
            "INELIGIBLE" if extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"} else
            evaluate_bi_eligibility(case).value
        )
    elif isinstance(case, BiCaseInput):
        update["eligibility"] = "UNKNOWN"
    if preflight:
        hypothesis, action, decision, rule_id, reason = preflight
        assessment = Assessment(
            hypothesis=hypothesis,
            confidence=Confidence.HIGH,
            missing_information=issues if hypothesis is Hypothesis.DATA_QUALITY_INVALID and not extra.get("pii_detected") and not extra.get("duplicate_of") else [],
            evidence_refs=[],
            summary=reason,
        )
        policy = PolicyResult(
            decision=decision,
            policy_version=(case.policy_version if isinstance(case, BiCaseInput) and case.policy_version else "DEMO-POLICY-0.1"),
            rules=[PolicyRule(rule_id=rule_id, result=RuleResult.FAIL, reason=reason)],
            triggering_rule_ids=[rule_id],
        )
        update.update({
            "assessment": assessment,
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


def assess_case(state: dict[str, Any], reasoner: Reasoner | DecisionReasoner | None = None) -> dict[str, Any]:
    selected_reasoner = reasoner or mock_reasoner
    decision = state.get("llm_decision")
    if decision is not None and decision.stage is DecisionStage.AFTER_EVENT:
        assessment = decision.assessment
    elif callable(getattr(selected_reasoner, "decide", None)):
        decision = selected_reasoner.decide(
            state["delivery_context"], state.get("evidence", []),
            stage=DecisionStage.INITIAL, case_input=state.get("case_input"),
        )
        if not isinstance(decision, AgentDecision):
            decision = AgentDecision.model_validate(decision)
        if decision.stage is not DecisionStage.INITIAL:
            raise ValueError("Initial decision stage did not match the graph stage.")
        known_ids = {item.evidence_id for item in state.get("evidence", [])}
        if not set(decision.evidence_refs + decision.assessment.evidence_refs) <= known_ids:
            raise ValueError("Initial decision referenced evidence outside the current evidence pack.")
        assessment = decision.assessment
    elif "case_input" in inspect.signature(selected_reasoner.assess).parameters:
        assessment = selected_reasoner.assess(
            state["delivery_context"], state.get("evidence", []), case_input=state.get("case_input")
        )
    else:  # Preserve compatibility with simple injected V0 reasoners.
        assessment = selected_reasoner.assess(state["delivery_context"], state.get("evidence", []))
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
    update = {"assessment": assessment, "missing_information": assessment.missing_information, "events": events}
    if decision is not None:
        update["llm_decision"] = decision
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
    can_change_action = bool(set(assessment.missing_information).intersection(askable_fields))
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
    decision: AgentDecision | None = state.get("llm_decision")
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
            should_wait = buyer_question_eligible if target == "BUYER" else needs_operational_event
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
    proposed = (
        Action.HOLD_DISRUPTION if case and case.disruption_signal.get("flag") and case.disruption_signal.get("verified") and not state.get("should_ask_buyer")
        else Action.ESCALATE_REVIEW if target == "SELLER" and case and any(item.get("outcome") == "invalid_number" for item in case.contact_evidence)
        else Action.CLARIFY if target in {"BUYER", "SELLER"} else Action.HOLD_DISRUPTION if target == "OPS" else Action.ESCALATE_REVIEW
    )
    update: dict[str, Any] = {
        "information_request": request,
        "proposed_action": proposed,
        "questions_asked": state.get("questions_asked", 0) + (1 if target == "BUYER" else 0),
        "case_status": CaseStatus.WAITING_FOR_BUYER if target == "BUYER" else CaseStatus.WAITING_FOR_EVENT,
        "events": events,
    }
    if case is not None:
        from .policy import evaluate_bi_recovery_policy
        policy = evaluate_bi_recovery_policy(
            proposed, case, state["assessment"],
            buyer_intent=state["delivery_context"].buyer_intent,
            event=state.get("case_event"),
        )
        update["recovery_policy_result"] = policy
        update["events"].append(execution_event(state, "generate_question", EventType.POLICY_EVALUATED, {
            "stage": "recovery", **policy.model_dump(mode="json"),
        }))
    return update


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
        return {"case_event": event, "buyer_reply": event.get("event_text", ""), "events": lifecycle_events(state, "wait_for_buyer")}
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


def parse_buyer_reply(state: dict[str, Any], reasoner: DecisionReasoner | None = None) -> dict[str, Any]:
    if reasoner is not None and callable(getattr(reasoner, "decide", None)):
        raw_event = state.get("case_event")
        reply = (state.get("buyer_reply") or "").strip()
        if isinstance(raw_event, CaseEvent):
            event = raw_event
        elif raw_event is not None:
            event = CaseEvent.model_validate(raw_event)
        else:
            event = CaseEvent(
                case_id=state["case_id"],
                event_type=BiEventType.BUYER_REPLY if reply else BiEventType.NO_REPLY,
                event_text=reply or None,
                reply_received=bool(reply),
            )
        decision = reasoner.decide(
            state["delivery_context"], state.get("evidence", []),
            stage=DecisionStage.AFTER_EVENT, case_input=state.get("case_input"), case_event=event,
        )
        if not isinstance(decision, AgentDecision):
            decision = AgentDecision.model_validate(decision)
        known_ids = {item.evidence_id for item in state.get("evidence", [])}
        if (
            decision.stage is not DecisionStage.AFTER_EVENT
            or decision.route is not DecisionRoute.PROPOSE_RECOVERY
            or decision.buyer_intent is None
            or not decision.parsed_facts
            or any(not key.strip() or not value.strip() for key, value in decision.parsed_facts.items())
            or decision.proposed_action is None
            or not set(decision.evidence_refs + decision.assessment.evidence_refs) <= known_ids
        ):
            raise ValueError("After-event decision does not satisfy the graph contract.")
        context = state["delivery_context"].model_copy(update={"buyer_intent": decision.buyer_intent})
        stamp = datetime.now(UTC).isoformat()
        evidence = [Evidence(
            evidence_id=f"{state['case_id']}:parsed:{key}:{state.get('iteration', 1)}",
            kind="parsed_event_fact", value=value,
            provenance="structured_case_event_extraction", timestamp=stamp,
            raw_text=event.event_text,
        ) for key, value in decision.parsed_facts.items()]
        resumed_state = {**state, "iteration": state.get("iteration", 1) + 1}
        events = [execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_STARTED)]
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.BUYER_REPLY_RECEIVED, {
            "event_type": event.event_type.value, "intent": decision.buyer_intent.value,
            "evidence_refs": [item.evidence_id for item in evidence],
        }))
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.STATE_TRANSITION, {
            "from": state.get("case_status", CaseStatus.WAITING_FOR_EVENT).value,
            "to": CaseStatus.RUNNING.value,
        }))
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_COMPLETED))
        return {
            "case_event": event,
            "buyer_reply": event.event_text or reply,
            "delivery_context": context,
            "llm_decision": decision,
            "parsed_facts": decision.parsed_facts,
            "evidence": evidence,
            "iteration": resumed_state["iteration"],
            "case_status": CaseStatus.RUNNING,
            "events": events,
        }
    raw_event = state.get("case_event")
    if raw_event:
        event = raw_event if isinstance(raw_event, CaseEvent) else CaseEvent.model_validate(raw_event)
        intent = event.buyer_intent or BuyerIntent.UNKNOWN
        reply = event.event_text or ""
        context = state["delivery_context"].model_copy(update={"buyer_intent": intent})
        evidence = Evidence(
            evidence_id=f"{state['case_id']}:event:{event.event_type.value}:{state.get('iteration', 1)}",
            kind=event.event_type.value.lower(),
            value=reply or event.event_type.value,
            provenance="simulated_bi_event",
            timestamp=datetime.now(UTC).isoformat(),
            raw_text=reply or None,
        )
        resumed_state = {**state, "iteration": state.get("iteration", 1) + 1}
        events = [execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_STARTED)]
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.BUYER_REPLY_RECEIVED, {
            "event_type": event.event_type.value, "intent": intent.value,
            "evidence_ref": evidence.evidence_id,
        }))
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.STATE_TRANSITION, {
            "from": state.get("case_status", CaseStatus.WAITING_FOR_EVENT).value,
            "to": CaseStatus.RUNNING.value,
        }))
        events.append(execution_event(resumed_state, "parse_buyer_reply", EventType.NODE_COMPLETED))
        return {
            "case_event": event,
            "buyer_reply": reply,
            "delivery_context": context,
            "evidence": [evidence],
            "iteration": resumed_state["iteration"],
            "case_status": CaseStatus.RUNNING,
            "events": events,
        }
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
    case: BiCaseInput | None = state.get("case_input")
    decision: AgentDecision | None = state.get("llm_decision")
    if case and case.extra_context.get("duplicate_of"):
        action = Action.NO_ACTION
    elif contact_result and contact_result.decision is not PolicyDecision.PERMITTED:
        action = Action.ESCALATE_REVIEW
    elif decision is not None and decision.route is DecisionRoute.PROPOSE_RECOVERY and decision.proposed_action is not None:
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
