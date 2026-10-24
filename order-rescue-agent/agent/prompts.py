"""All model-facing instructions for the synthetic Order Rescue agent."""

from __future__ import annotations

import json

from .schemas import AgentDecision, DecisionStage


def decision_system_prompt(stage: DecisionStage) -> str:
    common = (
        "Return exactly one AgentDecision JSON object. Required fields: stage, assessment, route. "
        "assessment requires hypothesis, confidence, missing_information, evidence_refs, summary. "
        "Use only the supplied evidence IDs; preserve the original source text and its actor. "
        "A courier note is an unverified report, not direct buyer confirmation. "
        "Never use an event that is not in the current input. "
        "Use only ASK or PROPOSE_RECOVERY as a route. Actions are CLARIFY, "
        "STANDARD_REATTEMPT, HOLD_DISRUPTION, ESCALATE_REVIEW, NO_ACTION. "
        "CLARIFY requires route ASK; do not put CLARIFY in a recovery proposal. "
        "The action is only a candidate. Do not evaluate policy, authorize execution, "
        "contact a real buyer, dispatch, change an address or payment, refund, or start a return. "
    )
    if stage is DecisionStage.INITIAL:
        stage_text = (
            "For INITIAL, assess the current evidence. If one buyer answer could change the recommendation, "
            "use ASK with target BUYER and an information_request. Only one simulated buyer question is allowed. "
            "Otherwise use PROPOSE_RECOVERY with a candidate action and rationale. "
            "Do not ask SELLER or OPS."
        )
    else:
        stage_text = (
            "For AFTER_EVENT, reassess using the newly available event and the full current evidence pack. "
            "Extract buyer_intent as UNKNOWN, WANTS, DECLINES, or CONDITIONAL, and provide parsed_facts. "
            "Use PROPOSE_RECOVERY with a candidate action and short rationale. "
            "For PROPOSE_RECOVERY, set target and information_request to null; do not draft another buyer question. "
            "Interpret a short buyer reply together with the original question, if supplied. "
            "A time answer to a question about receiving or availability supports willingness to receive unless hedged or contradicted. "
            "Treat that time as a preference, not a firm delivery promise; do not require an exact slot or a new address. "
            "If buyer intent remains unclear after the buyer reply, propose ESCALATE_REVIEW. "
            "A seller or operational event cannot establish buyer intent. "
            "Represent ambiguous intent or no reply as UNKNOWN; do not guess."
        )
    schema = json.dumps(AgentDecision.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return common + stage_text + " AgentDecision JSON Schema: " + schema


def assessment_system_prompt() -> str:
    return (
        "Assess this synthetic failed-delivery case using only the observable delivery context and evidence. "
        "Return one JSON object with exactly these fields: hypothesis, confidence, missing_information, "
        "evidence_refs, summary. Every field is required, including empty arrays. The shape is "
        '{"hypothesis":"UNKNOWN","confidence":"LOW","missing_information":[],"evidence_refs":[],"summary":"..."}. '
        "hypothesis must match the BI vocabulary: TEMP_AVAILABILITY_CONFLICT, ACCESS_RESTRICTION, "
        "ADDRESS_LANDMARK_UNCLEAR, ADDRESS_MISMATCH, LEGACY_ADMIN_ADDRESS, CONTACT_DATA_INVALID, "
        "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, REFUSAL_UNSUPPORTED, REFUSAL_CONFIRMED, "
        "BUYER_INTENT_UNCERTAIN, PAYMENT_OBSTACLE_COD, SERVICE_DISRUPTION, CAPACITY_PEAK, RECORD_CONFLICT, "
        "LIFECYCLE_CLOSED, PARCEL_DAMAGE, OUT_OF_SCOPE_REQUEST, OFF_SYSTEM_HOLD_SUSPECTED, "
        "SECURITY_INPUT_ANOMALY, DATA_QUALITY_INVALID, or UNKNOWN. confidence must be LOW, MEDIUM, "
        "or HIGH. Use only supplied evidence IDs in evidence_refs. Preserve uncertainty and do not infer "
        "facts that are not supported. missing_information contains missing BI fields or evidence needs, "
        "for example buyer_intent or decision_deadline. For RECIPIENT_UNAVAILABLE with unknown "
        "buyer intent, one unanswered call does not establish a persistently unreachable buyer: use "
        "TEMP_AVAILABILITY_CONFLICT at MEDIUM confidence and mark buyer_intent missing. Reserve "
        "BUYER_UNREACHABLE for repeated failed contact evidence or a confirmed invalid contact route. "
        "Do not propose an action, decide policy, or reveal chain-of-thought; "
        "summary must be a short evidence-grounded explanation."
    )
