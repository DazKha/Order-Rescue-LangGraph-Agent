import json
from pathlib import Path

import pytest

from agent.fixtures import load_bi_case, load_bi_event
from agent.graph import create_graph, thread_config
from langgraph.types import Command
from agent.policy import evaluate_bi_recovery_policy
from agent.schemas import Action, Assessment, BiCaseInput, BuyerIntent, Confidence, Hypothesis


DATA = Path(__file__).resolve().parents[1] / "data"
EXPECTED_ROWS = json.loads((DATA / "expected" / "bi_expected.json").read_text(encoding="utf-8"))
CASE_IDS = [row["case_id"] for row in EXPECTED_ROWS]


def bi_case(case_id: str) -> BiCaseInput:
    rows = json.loads((DATA / "fixtures" / "bi_inputs.json").read_text(encoding="utf-8"))
    return BiCaseInput.model_validate(next(row for row in rows if row["case_id"] == case_id))


def ready_assessment() -> Assessment:
    return Assessment(
        hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
        confidence=Confidence.HIGH,
        missing_information=[],
        evidence_refs=["OR-001:delivery-status"],
        summary="Buyer intent is explicit.",
    )


@pytest.mark.parametrize("case_id", ["OR-016", "OR-047"])
def test_unknown_return_or_deadline_escalates_standard_reattempt(case_id):
    case = bi_case(case_id)
    result = evaluate_bi_recovery_policy(Action.STANDARD_REATTEMPT, case, ready_assessment(), buyer_intent=BuyerIntent.WANTS)

    assert result.decision.value == "ESCALATED"


def test_return_started_blocks_standard_reattempt():
    result = evaluate_bi_recovery_policy(Action.STANDARD_REATTEMPT, bi_case("OR-015"), ready_assessment(), buyer_intent=BuyerIntent.WANTS)

    assert result.decision.value == "BLOCKED"


def test_conditional_exact_time_request_requires_review():
    result = evaluate_bi_recovery_policy(
        Action.STANDARD_REATTEMPT,
        bi_case("OR-053"),
        ready_assessment(),
        buyer_intent=BuyerIntent.CONDITIONAL,
        event=json.loads((DATA / "fixtures" / "bi_events.json").read_text(encoding="utf-8"))[52],
    )

    assert result.decision.value == "ESCALATED"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_full_bi_case_contract_and_stateful_event_resume(case_id):
    expected = next(row for row in EXPECTED_ROWS if row["case_id"] == case_id)
    graph = create_graph()
    config = thread_config(case_id)
    initial_result = graph.invoke(load_bi_case(case_id), config=config)
    state = graph.get_state(config).values

    assert state["assessment"].hypothesis.value == expected["1_hypothesis"]
    assert state["assessment"].confidence.value == expected["1_confidence"]
    expected_missing = sorted((expected.get("1_missing_information") or "").split(", ")) if expected.get("1_missing_information") else []
    assert sorted(state["assessment"].missing_information) == expected_missing
    assert state["proposed_action"].value == expected["1_candidate_action"]
    assert state["eligibility"] == expected["1_eligibility"]
    assert state["recovery_policy_result"].decision.value == expected["1_policy_gate"]
    if expected["1_question_needed"] == "YES":
        assert state["should_wait_event"]
        assert state["event_target"] in {"BUYER", "SELLER"}
        if state["event_target"] == "BUYER":
            assert state["should_ask_buyer"]
    else:
        assert not state["should_ask_buyer"]

    event = load_bi_event(case_id)
    if not initial_result.get("__interrupt__") or event is None:
        return

    resumed = graph.invoke(Command(resume={"case_event": event.model_dump(mode="json")}), config=config)
    updated = graph.get_state(config).values if resumed.get("__interrupt__") else resumed
    if expected.get("2_hypothesis"):
        assert updated["assessment"].hypothesis.value == expected["2_hypothesis"]
    if expected.get("2_confidence"):
        assert updated["assessment"].confidence.value == expected["2_confidence"]
    if expected.get("2_candidate_action"):
        assert updated["proposed_action"].value == expected["2_candidate_action"]
    if expected.get("2_policy_gate"):
        assert updated["recovery_policy_result"].decision.value == expected["2_policy_gate"]
    if resumed.get("__interrupt__") and expected.get("2_candidate_action") == "CLARIFY":
        assert updated["event_target"] == "BUYER"
        assert updated["should_ask_buyer"]

    assert all(not item.executed for item in [updated.get("final_recommendation")] if item is not None)
