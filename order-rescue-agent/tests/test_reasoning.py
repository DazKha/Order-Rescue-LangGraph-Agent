import json
import pytest
from pydantic import ValidationError

from agent.reasoning import DeepSeekReasoner
from agent.schemas import (
    Action,
    AgentDecision,
    Assessment,
    BuyerIntent,
    Confidence,
    DecisionRoute,
    DecisionStage,
    DecisionTarget,
    DeliveryContext,
    Evidence,
    Hypothesis,
    InformationRequest,
)
from agent.fixtures import load_bi_case, load_bi_event


def test_deepseek_reasoner_sends_observed_inputs_and_validates_json():
    calls = []

    def transport(url, *, headers, body, timeout):
        calls.append((url, headers, json.loads(body), timeout))
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
                    "confidence": "MEDIUM",
                    "missing_information": ["buyer_intent"],
                    "evidence_refs": ["OR-001:delivery-status"],
                    "summary": "Buyer intent is not yet known.",
                })},
            }]
        }

    reasoner = DeepSeekReasoner(api_key="test-secret", transport=transport)
    result = reasoner.assess(
        DeliveryContext(delivery_status="RECIPIENT_UNAVAILABLE", attempt_count=1, attempt_limit=3),
        [Evidence(
            evidence_id="OR-001:delivery-status",
            kind="delivery_status",
            value="RECIPIENT_UNAVAILABLE",
            provenance="synthetic_delivery_event",
            timestamp="2026-10-18T00:00:00Z",
        )],
    )

    assert result.hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT
    assert result.confidence is Confidence.MEDIUM
    assert result.missing_information == ["buyer_intent"]
    assert len(calls) == 1
    url, headers, body, timeout = calls[0]
    assert url == "https://api.deepseek.com/chat/completions"
    assert headers["Authorization"] == "Bearer test-secret"
    assert body["response_format"] == {"type": "json_object"}
    assert "expected_action" not in body["messages"][1]["content"]
    assert timeout > 0


def test_confirmed_buyer_intent_clears_intent_gap_and_raises_confidence():
    def transport(url, *, headers, body, timeout):
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
                    "confidence": "MEDIUM",
                    "missing_information": ["buyer_intent"],
                    "evidence_refs": ["OR-001:buyer-intent"],
                    "summary": "Buyer confirmed they still want delivery.",
                })},
            }]
        }

    result = DeepSeekReasoner(api_key="test-secret", transport=transport).assess(
        DeliveryContext(
            delivery_status="RECIPIENT_UNAVAILABLE",
            attempt_count=1,
            attempt_limit=3,
            buyer_intent="WANTS",
        ),
        [Evidence(
            evidence_id="OR-001:buyer-intent",
            kind="buyer_intent",
            value="WANTS",
            provenance="synthetic_buyer_reply",
            timestamp="2026-10-18T00:00:00Z",
        )],
    )

    assert result.confidence is Confidence.HIGH
    assert "buyer_intent" not in result.missing_information


def test_deepseek_accepts_bi_specific_missing_information_fields():
    def transport(url, *, headers, body, timeout):
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "hypothesis": "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE",
                    "confidence": "LOW",
                    "missing_information": ["decision_deadline", "return_state"],
                    "evidence_refs": ["OR-001:delivery-status"],
                    "summary": "Unknown field from model output.",
                })},
            }]
        }

    reasoner = DeepSeekReasoner(api_key="test-secret", transport=transport)
    result = reasoner.assess(
        DeliveryContext(delivery_status="RECIPIENT_UNAVAILABLE"),
        [Evidence(
            evidence_id="OR-001:delivery-status",
            kind="delivery_status",
            value="RECIPIENT_UNAVAILABLE",
            provenance="synthetic_delivery_event",
            timestamp="2026-10-18T00:00:00Z",
        )],
    )
    assert result.hypothesis.value == "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE"
    assert result.missing_information == ["decision_deadline", "return_state"]


def test_deepseek_receives_bi_inputs_but_not_hidden_events_or_expected_labels():
    calls = []

    def transport(url, *, headers, body, timeout):
        calls.append(json.loads(body))
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
                    "confidence": "MEDIUM",
                    "missing_information": ["buyer_intent"],
                    "evidence_refs": [],
                    "summary": "Initial BI input does not establish buyer intent.",
                })},
            }]
        }

    state = load_bi_case("OR-001")
    hidden_event = load_bi_event("OR-001")
    result = DeepSeekReasoner(api_key="test-secret", transport=transport).assess(
        state["delivery_context"], [], case_input=state["case_input"]
    )
    model_input = json.loads(calls[0]["messages"][1]["content"])

    assert result.hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT
    assert model_input["case_input"]["case_id"] == "OR-001"
    assert "event_text" not in model_input
    assert hidden_event.event_text not in calls[0]["messages"][1]["content"]
    assert "1_hypothesis" not in calls[0]["messages"][1]["content"]
    assert "expected_action" not in calls[0]["messages"][1]["content"]


def test_agent_decision_accepts_initial_buyer_question():
    decision = AgentDecision(
        stage=DecisionStage.INITIAL,
        assessment=Assessment(
            hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
            confidence=Confidence.MEDIUM,
            missing_information=["buyer_intent"],
            evidence_refs=["OR-001:courier-note"],
            summary="Buyer intent is unknown.",
        ),
        route=DecisionRoute.ASK,
        target=DecisionTarget.BUYER,
        information_request=InformationRequest(
            question="Do you still want delivery?",
            purpose="Confirm buyer intent.",
        ),
    )
    assert decision.route is DecisionRoute.ASK


def test_agent_decision_accepts_unknown_after_event_intent():
    decision = AgentDecision(
        stage=DecisionStage.AFTER_EVENT,
        assessment=Assessment(
            hypothesis=Hypothesis.BUYER_INTENT_UNCERTAIN,
            confidence=Confidence.LOW,
            missing_information=["buyer_intent"],
            evidence_refs=["OR-001:event:BUYER_REPLY:1"],
            summary="The reply is ambiguous.",
        ),
        route=DecisionRoute.PROPOSE_RECOVERY,
        buyer_intent=BuyerIntent.UNKNOWN,
        proposed_action=Action.ESCALATE_REVIEW,
        rationale="Intent remains unclear.",
    )
    assert decision.buyer_intent is BuyerIntent.UNKNOWN


def test_agent_decision_rejects_unregistered_route():
    payload = {
        "stage": "INITIAL",
        "assessment": {
            "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
            "confidence": "MEDIUM",
            "missing_information": ["buyer_intent"],
            "evidence_refs": ["OR-001:courier-note"],
            "summary": "Buyer intent is unknown.",
        },
        "route": "CALL_ANY_NODE",
        "target": "BUYER",
        "information_request": {
            "question": "Do you still want delivery?",
            "purpose": "Confirm buyer intent.",
            "simulated": True,
        },
    }
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(payload)
