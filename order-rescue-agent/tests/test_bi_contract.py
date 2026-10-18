import json
from pathlib import Path

from agent.bi_adapter import validate_case_input
from agent.fixtures import load_bi_case, load_bi_event
from agent.graph import create_graph, thread_config
from agent.reasoning import DeterministicMockReasoner
from agent.schemas import Action, BiCaseInput, BuyerIntent, CaseEvent, EventType, Hypothesis, PolicyDecision, ReturnState


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_bi_vocabularies_are_preserved():
    assert {"ACCESS_RESTRICTION", "ADDRESS_LANDMARK_UNCLEAR", "DATA_QUALITY_INVALID"} <= {
        value.value for value in Hypothesis
    }
    assert {"WANTS", "DECLINES", "CONDITIONAL", "UNKNOWN"} <= {
        value.value for value in BuyerIntent
    }
    assert {"PERMITTED", "BLOCKED", "ESCALATED"} <= {
        value.value for value in PolicyDecision
    }
    assert {"NOT_STARTED", "STARTED", "COMPLETED", "UNKNOWN"} <= {
        value.value for value in ReturnState
    }
    assert {"CLARIFY", "STANDARD_REATTEMPT", "HOLD_DISRUPTION", "ESCALATE_REVIEW", "NO_ACTION"} == {
        value.value for value in Action
    }


def test_bi_cases_keep_inputs_events_and_expected_outputs_separate():
    inputs = json.loads((DATA_DIR / "fixtures" / "bi_inputs.json").read_text(encoding="utf-8"))
    events = json.loads((DATA_DIR / "fixtures" / "bi_events.json").read_text(encoding="utf-8"))
    expected = json.loads((DATA_DIR / "expected" / "bi_expected.json").read_text(encoding="utf-8"))

    assert len(inputs) == len(events) == len(expected) == 56
    assert [item["case_id"] for item in inputs] == [item["case_id"] for item in expected]
    assert all(not any(key.startswith(("1_", "2_", "FINAL_")) for key in item) for item in inputs)
    assert next(item for item in inputs if item["case_id"] == "OR-052")["courier_note"].startswith("Synthetic PII marker")
    assert next(item for item in events if item["case_id"] == "OR-001")["event_type"] == "BUYER_REPLY"


def test_all_bi_input_rows_match_typed_case_schema():
    inputs = json.loads((DATA_DIR / "fixtures" / "bi_inputs.json").read_text(encoding="utf-8"))

    cases = [BiCaseInput.model_validate(item) for item in inputs]

    assert len(cases) == 56
    assert cases[0].raw_status == "RECIPIENT_UNAVAILABLE"
    assert cases[0].attempts_remaining == 2


def test_bi_events_match_event_schema_and_use_bi_intents():
    events = json.loads((DATA_DIR / "fixtures" / "bi_events.json").read_text(encoding="utf-8"))
    or001 = next(item for item in events if item["case_id"] == "OR-001")

    parsed = CaseEvent.model_validate(or001)

    assert parsed.event_type is EventType.BUYER_REPLY
    assert parsed.buyer_intent is BuyerIntent.WANTS


def test_reasoner_assesses_from_bi_case_input():
    state = load_bi_case("OR-001")
    assessment = DeterministicMockReasoner().assess(
        state["delivery_context"], [], case_input=state["case_input"]
    )

    assert assessment.hypothesis.value == "TEMP_AVAILABILITY_CONFLICT"
    assert assessment.confidence.value == "MEDIUM"
    assert "buyer_intent" in assessment.missing_information


def test_bi_invalid_input_fails_closed_with_field_reasons():
    inputs = json.loads((DATA_DIR / "fixtures" / "bi_inputs.json").read_text(encoding="utf-8"))
    invalid = next(item for item in inputs if item["case_id"] == "OR-056")

    result = validate_case_input(invalid)

    assert not result.valid
    assert "failed_at" in result.issues
    assert "raw_status" in result.issues
    assert "policy_version" in result.issues


def test_fixture_loader_hides_later_event_until_requested():
    initial = load_bi_case("OR-001")

    assert initial["case_id"] == "OR-001"
    assert "case_input" in initial
    assert initial["case_event"] is None
    assert "1_hypothesis" not in initial["case_input"]

    later_event = load_bi_event("OR-001")
    assert later_event.event_type is EventType.BUYER_REPLY
    assert later_event.buyer_intent is BuyerIntent.WANTS


def test_invalid_bi_case_is_blocked_before_any_interrupt():
    graph = create_graph()
    initial = load_bi_case("OR-056")

    result = graph.invoke(initial, config=thread_config("OR-056"))

    assert not result.get("__interrupt__")
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
    assert result["final_recommendation"].policy_decision.value == "BLOCKED"


def test_pii_prompt_injection_and_stale_cases_are_gated_before_assessment():
    expectations = {
        "OR-051": ("SECURITY_INPUT_ANOMALY", "ESCALATE_REVIEW", "ESCALATED"),
        "OR-052": ("DATA_QUALITY_INVALID", "ESCALATE_REVIEW", "BLOCKED"),
        "OR-055": ("DATA_QUALITY_INVALID", "NO_ACTION", "BLOCKED"),
    }
    for case_id, (hypothesis, action, decision) in expectations.items():
        graph = create_graph()
        result = graph.invoke(load_bi_case(case_id), config=thread_config(case_id))

        assert result["assessment"].hypothesis.value == hypothesis
        assert result["final_recommendation"].action.value == action
        assert result["final_recommendation"].policy_decision.value == decision
        assert not result.get("__interrupt__")
