from langgraph.types import Command

from agent.events import EventType
from agent.fixtures import load_or_001
from agent.graph import create_graph, thread_config
from agent.nodes import assess_case
from agent.reasoning import DeterministicMockReasoner
from agent.schemas import Action, CaseStatus, Confidence, DeliveryContext, Hypothesis, PolicyDecision


def begin_or_001():
    graph = create_graph()
    initial = load_or_001()
    config = thread_config(initial["case_id"])
    result = graph.invoke(initial, config=config)
    return graph, config, result


def resume(graph, config, reply="Yesterday I was at work and missed the call. I still want delivery."):
    return graph.invoke(Command(resume={"text": reply}), config=config)


def test_initial_assessment_identifies_missing_intent():
    state = load_or_001()
    update = assess_case(state)
    assert update["assessment"].hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT
    assert update["assessment"].confidence is Confidence.MEDIUM
    assert "buyer_intent" in update["assessment"].missing_information


def test_agent_interrupts_when_buyer_clarification_needed():
    graph, config, result = begin_or_001()
    assert result.get("__interrupt__")
    assert graph.get_state(config).values["case_status"] is CaseStatus.WAITING_FOR_BUYER


def test_buyer_reply_triggers_reassessment():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    assessments = [e for e in result["events"] if e.event_type == EventType.ASSESSMENT_COMPLETED]
    assert len(assessments) >= 2
    assert result["assessment"].confidence is Confidence.HIGH
    assert result["proposed_action"] is Action.STANDARD_REATTEMPT


def test_evidence_is_preserved_after_resume():
    graph, config, _ = begin_or_001()
    before = graph.get_state(config).values["evidence"]
    result = resume(graph, config)
    ids_before = {item.evidence_id for item in before}
    ids_after = {item.evidence_id for item in result["evidence"]}
    assert ids_before <= ids_after
    assert any(item.provenance == "simulated_buyer_reply" for item in result["evidence"])


def test_buyer_question_is_not_duplicated():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    questions = [e for e in result["events"] if e.event_type == EventType.INFORMATION_REQUESTED]
    assert len(questions) == 1
    assert result["questions_asked"] == 1
    assert len(result["evidence"]) == 3


def test_buyer_reply_records_transition_back_to_running():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    transitions = [
        event for event in result["events"]
        if event.event_type == EventType.STATE_TRANSITION
        and event.payload.get("from") == CaseStatus.WAITING_FOR_BUYER.value
    ]
    assert len(transitions) == 1
    assert transitions[0].payload["to"] == CaseStatus.RUNNING.value


def test_ambiguous_reply_preserves_uncertainty_and_routes_to_review():
    graph, config, _ = begin_or_001()
    result = resume(graph, config, "I missed the call yesterday.")
    assert result["delivery_context"].buyer_intent.value == "UNKNOWN"
    assert result["assessment"].confidence is Confidence.MEDIUM
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW


def test_explicit_negative_delivery_intent_never_becomes_a_reattempt():
    for reply in ("I no longer want delivery.", "I don't want delivery."):
        graph, config, _ = begin_or_001()
        result = resume(graph, config, reply)

        assert result["delivery_context"].buyer_intent.value == "DOES_NOT_WANT_DELIVERY"
        assert result["proposed_action"] is Action.NO_ACTION
        assert result["final_recommendation"].action is Action.NO_ACTION


def test_final_recommendation_requires_policy_check():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    kinds = [event.event_type for event in result["events"]]
    recovery_policy_index = next(i for i, event in enumerate(result["events"])
                                 if event.event_type == EventType.POLICY_EVALUATED and event.payload.get("stage") == "recovery")
    recommendation_index = next(i for i, event in enumerate(result["events"])
                                if event.event_type == EventType.RECOMMENDATION_PUBLISHED)
    assert recovery_policy_index < recommendation_index
    assert result["final_recommendation"].policy_decision is PolicyDecision.PERMITTED


def test_no_real_logistics_action_is_executed():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    recommendation = result["final_recommendation"]
    assert recommendation.action is Action.STANDARD_REATTEMPT
    assert recommendation.executed is False
    assert recommendation.side_effects == []


def test_or_001_end_to_end_reassesses_and_recommends_safely():
    graph, config, _ = begin_or_001()
    result = resume(graph, config)
    assert result["assessment"].confidence is Confidence.HIGH
    assert result["final_recommendation"].action is Action.STANDARD_REATTEMPT
    assert result["final_recommendation"].policy_decision is PolicyDecision.PERMITTED
    assert result["case_status"] is CaseStatus.COMPLETED
    assert sum(e.event_type == EventType.ASSESSMENT_COMPLETED for e in result["events"]) >= 2
    recovery_policy_index = next(i for i, event in enumerate(result["events"])
                                 if event.event_type == EventType.POLICY_EVALUATED and event.payload.get("stage") == "recovery")
    recommendation_index = next(i for i, event in enumerate(result["events"])
                                if event.event_type == EventType.RECOMMENDATION_PUBLISHED)
    assert recovery_policy_index < recommendation_index


def test_injected_reasoner_runs_for_initial_and_resumed_assessments():
    class SpyReasoner:
        def __init__(self):
            self.calls = []

        def assess(self, context, evidence):
            self.calls.append((context.buyer_intent, [item.provenance for item in evidence]))
            return DeterministicMockReasoner().assess(context, evidence)

    reasoner = SpyReasoner()
    graph = create_graph(reasoner=reasoner)
    initial = load_or_001()
    config = thread_config(initial["case_id"])
    graph.invoke(initial, config=config)
    result = resume(graph, config)
    assert len(reasoner.calls) == 2
    assert "simulated_buyer_reply" not in reasoner.calls[0][1]
    assert "simulated_buyer_reply" in reasoner.calls[1][1]
    assert result["final_recommendation"].action is Action.STANDARD_REATTEMPT


def test_retry_is_blocked_if_return_starts_while_waiting():
    graph, config, _ = begin_or_001()
    snapshot = graph.get_state(config).values
    context_data = snapshot["delivery_context"].model_dump(mode="json")
    context_data["return_state"] = "STARTED"
    graph.update_state(config, {"delivery_context": DeliveryContext.model_validate(context_data)})
    result = resume(graph, config)
    assert result["proposed_action"] is Action.STANDARD_REATTEMPT
    assert result["recovery_policy_result"].decision is PolicyDecision.BLOCKED
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
