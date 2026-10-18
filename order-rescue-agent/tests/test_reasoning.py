import json
import pytest

from agent.reasoning import DeepSeekReasoner
from agent.schemas import Confidence, DeliveryContext, Evidence, Hypothesis


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
            buyer_intent="WANTS_DELIVERY",
        ),
        [Evidence(
            evidence_id="OR-001:buyer-intent",
            kind="buyer_intent",
            value="WANTS_DELIVERY",
            provenance="synthetic_buyer_reply",
            timestamp="2026-10-18T00:00:00Z",
        )],
    )

    assert result.confidence is Confidence.HIGH
    assert "buyer_intent" not in result.missing_information


def test_deepseek_rejects_unregistered_missing_information_values():
    def transport(url, *, headers, body, timeout):
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "hypothesis": "UNKNOWN",
                    "confidence": "LOW",
                    "missing_information": ["refund_status"],
                    "evidence_refs": ["OR-001:delivery-status"],
                    "summary": "Unknown field from model output.",
                })},
            }]
        }

    reasoner = DeepSeekReasoner(api_key="test-secret", transport=transport)
    with pytest.raises(RuntimeError, match="missing_information"):
        reasoner.assess(
            DeliveryContext(delivery_status="RECIPIENT_UNAVAILABLE"),
            [Evidence(
                evidence_id="OR-001:delivery-status",
                kind="delivery_status",
                value="RECIPIENT_UNAVAILABLE",
                provenance="synthetic_delivery_event",
                timestamp="2026-10-18T00:00:00Z",
            )],
        )
