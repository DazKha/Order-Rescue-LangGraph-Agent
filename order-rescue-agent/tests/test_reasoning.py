import json
import pytest
from pydantic import ValidationError

from agent.reasoning import DeepSeekReasoner
from agent.schemas import (
    Action,
    AgentDecision,
    Assessment,
    BuyerIntent,
    CaseEvent,
    Confidence,
    DecisionRoute,
    DecisionStage,
    DecisionTarget,
    DeliveryContext,
    Evidence,
    EventType,
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


def fake_transport(response_json, captured):
    def send(url, *, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["request"] = json.loads(body)
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps(response_json)},
            }]
        }
    return send


def _decision_payload(stage="INITIAL", route="ASK"):
    result = {
        "stage": stage,
        "assessment": {
            "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
            "confidence": "MEDIUM",
            "missing_information": ["buyer_intent"],
            "evidence_refs": ["OR-001:delivery-status"],
            "summary": "Buyer intent is unknown.",
        },
        "route": route,
        "evidence_refs": ["OR-001:delivery-status"],
    }
    if route == "ASK":
        result.update(target="BUYER", information_request={
            "question": "Do you still want delivery?", "purpose": "Confirm intent."
        })
    elif route == "WAIT_FOR_EVENT":
        result["target"] = "OPS"
    else:
        result.update(proposed_action="ESCALATE_REVIEW", rationale="Review the case.")
    if stage == "AFTER_EVENT":
        result.update(buyer_intent="WANTS", parsed_facts={"reply": "wants delivery"})
    return result


def _decision_inputs():
    state = load_bi_case("OR-001")
    evidence = [Evidence(
        evidence_id="OR-001:delivery-status", kind="delivery_status",
        value="RECIPIENT_UNAVAILABLE", provenance="synthetic_delivery_event",
        timestamp="2026-10-18T00:00:00Z",
    )]
    return state, evidence


def _no_reply_event():
    return CaseEvent(
        case_id="OR-001", event_type=EventType.NO_REPLY,
        event_text=None, reply_received=False, buyer_intent=BuyerIntent.UNKNOWN,
    )


def test_decide_initial_sends_observable_inputs_and_returns_ask():
    captured = {}
    state, evidence = _decision_inputs()
    result = DeepSeekReasoner(api_key="test-secret", transport=fake_transport(
        _decision_payload(), captured,
    )).decide(state["delivery_context"], evidence, stage=DecisionStage.INITIAL,
              case_input=state["case_input"])

    assert isinstance(result, AgentDecision)
    assert result.route is DecisionRoute.ASK
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["request"]["stream"] is False
    user = json.loads(captured["request"]["messages"][1]["content"])
    assert user["stage"] == "INITIAL"
    assert user["case_input"]["case_id"] == "OR-001"
    assert user["evidence"][0]["evidence_id"] == "OR-001:delivery-status"
    assert "case_event" not in user


def test_decide_after_event_sends_raw_event_and_returns_candidate():
    captured = {}
    state, evidence = _decision_inputs()
    event = load_bi_event("OR-001")
    result = DeepSeekReasoner(api_key="test-secret", transport=fake_transport(
        _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY"), captured,
    )).decide(state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT,
              case_input=state["case_input"], case_event=event)

    assert isinstance(result, AgentDecision)
    assert result.proposed_action is Action.ESCALATE_REVIEW
    user = json.loads(captured["request"]["messages"][1]["content"])
    assert user["stage"] == "AFTER_EVENT"
    assert user["case_event"]["event_text"] == event.event_text


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(route="CALL_ANY_NODE"),
    lambda p: p.pop("target"),
    lambda p: p.pop("information_request"),
    lambda p: p["assessment"].update(evidence_refs=["unknown-id"]),
    lambda p: p.update(evidence_refs=["unknown-id"]),
    lambda p: p.update(stage="AFTER_EVENT"),
])
def test_decide_rejects_invalid_or_unsupported_results_without_leaking_secret(mutate):
    payload = _decision_payload()
    mutate(payload)
    state, evidence = _decision_inputs()
    reasoner = DeepSeekReasoner(api_key="test-secret", transport=fake_transport(payload, {}))
    with pytest.raises(RuntimeError) as exc:
        reasoner.decide(state["delivery_context"], evidence, stage=DecisionStage.INITIAL)
    assert "test-secret" not in str(exc.value)
    assert "Authorization" not in str(exc.value)


def test_decide_rejects_malformed_json_without_leaking_secret():
    def send(url, *, headers, body, timeout):
        return {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"secret":"test-secret",',
        }}]}
    state, evidence = _decision_inputs()
    with pytest.raises(RuntimeError) as exc:
        DeepSeekReasoner(api_key="test-secret", transport=send).decide(
            state["delivery_context"], evidence, stage=DecisionStage.INITIAL,
        )
    assert "test-secret" not in str(exc.value)


@pytest.mark.parametrize("route", ["WAIT_FOR_EVENT", "PROPOSE_RECOVERY"])
def test_decide_initial_accepts_other_allowlisted_routes(route):
    state, evidence = _decision_inputs()
    decision = DeepSeekReasoner(api_key="test-secret", transport=fake_transport(
        _decision_payload(route=route), {},
    )).decide(state["delivery_context"], evidence, stage=DecisionStage.INITIAL)
    assert decision.route.value == route


def test_decide_sanitizes_transport_failures():
    def send(url, *, headers, body, timeout):
        raise RuntimeError("Authorization: Bearer test-secret")
    state, evidence = _decision_inputs()
    with pytest.raises(RuntimeError) as exc:
        DeepSeekReasoner(api_key="test-secret", transport=send).decide(
            state["delivery_context"], evidence, stage=DecisionStage.INITIAL,
        )
    assert "test-secret" not in str(exc.value)
    assert "Authorization" not in str(exc.value)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(proposed_action="REFUND"),
    lambda p: p.pop("proposed_action"),
    lambda p: p.pop("buyer_intent"),
    lambda p: p.update(route="WAIT_FOR_EVENT"),
])
def test_decide_after_event_rejects_missing_or_invalid_fields(mutate):
    payload = _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY")
    mutate(payload)
    state, evidence = _decision_inputs()
    with pytest.raises(RuntimeError):
        DeepSeekReasoner(api_key="test-secret", transport=fake_transport(payload, {})).decide(
            state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT,
            case_event=load_bi_event("OR-001"),
        )


def test_decide_after_event_requires_raw_event_before_transport():
    state, evidence = _decision_inputs()
    captured = {}
    with pytest.raises(RuntimeError):
        DeepSeekReasoner(api_key="test-secret", transport=fake_transport(
            _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY"), captured,
        )).decide(state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT)
    assert captured == {}


@pytest.mark.parametrize("facts", [{}, {"reply": "  "}])
def test_decide_after_event_rejects_empty_extraction(facts):
    state, evidence = _decision_inputs()
    payload = _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY")
    payload["parsed_facts"] = facts
    with pytest.raises(RuntimeError):
        DeepSeekReasoner(api_key="test-secret", transport=fake_transport(payload, {})).decide(
            state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT,
            case_event=load_bi_event("OR-001"),
        )


@pytest.mark.parametrize("event", [
    _no_reply_event(),
    CaseEvent(case_id="OR-001", event_type=EventType.BUYER_REPLY,
              event_text="Maybe; I am not sure.", reply_received=True,
              buyer_intent=BuyerIntent.UNKNOWN),
])
def test_decide_after_event_rejects_intent_conflicting_with_unknown_event(event):
    state, evidence = _decision_inputs()
    payload = _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY")
    payload["parsed_facts"] = {"reply_status": "no reply"}
    with pytest.raises(RuntimeError) as exc:
        DeepSeekReasoner(api_key="test-secret", transport=fake_transport(payload, {})).decide(
            state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT,
            case_event=event,
        )
    assert "test-secret" not in str(exc.value)


def test_decide_after_event_accepts_unknown_intent_with_no_reply_fact():
    state, evidence = _decision_inputs()
    payload = _decision_payload("AFTER_EVENT", "PROPOSE_RECOVERY")
    payload.update(buyer_intent="UNKNOWN", parsed_facts={"reply_status": "no reply"})
    decision = DeepSeekReasoner(api_key="test-secret", transport=fake_transport(payload, {})).decide(
        state["delivery_context"], evidence, stage=DecisionStage.AFTER_EVENT,
        case_event=_no_reply_event(),
    )
    assert decision.buyer_intent is BuyerIntent.UNKNOWN
