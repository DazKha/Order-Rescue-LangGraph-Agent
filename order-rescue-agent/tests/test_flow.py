import pytest

from langgraph.types import Command

from agent.events import EventType
from agent.fixtures import load_bi_event, load_or_001
from agent.graph import create_graph, thread_config
from agent.nodes import assess_case
from agent.reasoning import DeterministicMockReasoner
from agent.schemas import (
    Action, AgentDecision, Assessment, BuyerIntent, CaseStatus, Confidence,
    DecisionRoute, DecisionStage, DeliveryContext, Hypothesis,
    InformationRequest, PolicyDecision,
)


class FakeDecisionProvider:
    def __init__(
        self, *, after_action=Action.STANDARD_REATTEMPT,
        after_intent=BuyerIntent.WANTS, initial_missing=None,
        initial_route=DecisionRoute.ASK, initial_target="BUYER",
        initial_question="Do you still want this delivery?",
    ):
        self.calls = []
        self.after_action = after_action
        self.after_intent = after_intent
        self.after_missing = []
        self.initial_missing = ["buyer_intent"] if initial_missing is None else initial_missing
        self.initial_route = initial_route
        self.initial_target = initial_target
        self.initial_question = initial_question

    def decide(self, context, evidence, *, stage, case_input=None, case_event=None):
        self.calls.append((stage, case_event, tuple(evidence)))
        refs = [item.evidence_id for item in evidence]
        if stage is DecisionStage.INITIAL:
            return AgentDecision(
                stage=stage,
                assessment=Assessment(
                    hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
                    confidence=Confidence.MEDIUM,
                    missing_information=self.initial_missing,
                    evidence_refs=refs,
                    summary="Buyer intent needs confirmation.",
                ),
                route=self.initial_route,
                target=self.initial_target,
                information_request=InformationRequest(
                    question=self.initial_question,
                    purpose="Confirm buyer intent before recovery.",
                ) if self.initial_route is DecisionRoute.ASK else None,
                evidence_refs=refs,
            )
        assert stage is DecisionStage.AFTER_EVENT
        assert case_event is not None
        return AgentDecision(
            stage=stage,
            assessment=Assessment(
                hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
                confidence=Confidence.HIGH,
                missing_information=self.after_missing,
                evidence_refs=refs,
                summary="The event gives the buyer's intent.",
            ),
            route=DecisionRoute.PROPOSE_RECOVERY,
            buyer_intent=self.after_intent,
            parsed_facts={"reply": "Buyer gave a direct response."},
            proposed_action=self.after_action,
            rationale="Apply the recorded reply to recovery planning.",
            evidence_refs=refs,
        )


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
    assert len(result["evidence"]) >= 3


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

        assert result["delivery_context"].buyer_intent.value == "DECLINES"
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
    case_data = snapshot["case_input"].model_dump(mode="json")
    case_data["return_state"] = "started"
    from agent.schemas import BiCaseInput
    graph.update_state(config, {
        "delivery_context": DeliveryContext.model_validate(context_data),
        "case_input": BiCaseInput.model_validate(case_data),
    })
    result = resume(graph, config)
    assert result["proposed_action"] is Action.ESCALATE_REVIEW
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
    assert result["final_recommendation"].executed is False


def test_staged_decision_waits_then_uses_rebuilt_event_evidence_for_one_resume_decision():
    provider = FakeDecisionProvider()
    graph = create_graph(reasoner=provider)
    initial = load_or_001()
    config = thread_config(initial["case_id"])

    paused = graph.invoke(initial, config=config)
    assert paused.get("__interrupt__")
    assert len(provider.calls) == 1
    assert provider.calls[0][0] is DecisionStage.INITIAL
    assert graph.get_state(config).values["information_request"].question == "Do you still want this delivery?"

    event = load_bi_event("OR-001")
    result = graph.invoke(Command(resume={"case_event": event.model_dump(mode="json")}), config=config)

    assert len(provider.calls) == 2
    stage, observed_event, observed_evidence = provider.calls[1]
    assert stage is DecisionStage.AFTER_EVENT
    assert observed_event.event_type is event.event_type
    assert any(item.raw_text == event.event_text for item in observed_evidence)
    assert result["delivery_context"].buyer_intent is BuyerIntent.WANTS
    assert result["llm_decision"].parsed_facts["reply"] == "Buyer gave a direct response."
    assert result["parsed_facts"]["reply"] == "Buyer gave a direct response."
    assert any(item.kind == "parsed_event_fact" and item.value == "Buyer gave a direct response."
               for item in result["evidence"])
    assert result["proposed_action"] is Action.STANDARD_REATTEMPT
    assert result["recovery_policy_result"] is not None
    assert result["case_status"] is CaseStatus.COMPLETED


def test_staged_ask_cannot_use_invalid_buyer_contact():
    provider = FakeDecisionProvider()
    state = load_or_001()
    state["case_input"] = state["case_input"].model_copy(update={
        "contact_evidence": [{"outcome": "invalid_number"}],
    })
    result = create_graph(reasoner=provider).invoke(state, config=thread_config(state["case_id"]))

    assert not result.get("__interrupt__")
    assert result["contact_policy_result"].decision is not PolicyDecision.PERMITTED
    assert result.get("information_request") is None
    assert result["questions_asked"] == 0
    assert len(provider.calls) == 1


def test_staged_ask_cannot_exceed_one_question():
    provider = FakeDecisionProvider()
    state = load_or_001()
    state["questions_asked"] = 1
    result = create_graph(reasoner=provider).invoke(state, config=thread_config(state["case_id"]))

    assert not result.get("__interrupt__")
    assert result["contact_policy_result"].decision is not PolicyDecision.PERMITTED
    assert result.get("information_request") is None
    assert result["questions_asked"] == 1


def test_staged_ask_without_actionable_missing_information_does_not_generate_question():
    provider = FakeDecisionProvider(initial_missing=[])
    state = load_or_001()
    result = create_graph(reasoner=provider).invoke(state, config=thread_config(state["case_id"]))

    assert not result.get("__interrupt__")
    assert result["contact_policy_result"].decision is PolicyDecision.PERMITTED
    assert result.get("information_request") is None
    assert result["questions_asked"] == 0


def test_staged_wait_without_information_need_or_operational_event_does_not_interrupt():
    provider = FakeDecisionProvider(
        initial_route=DecisionRoute.WAIT_FOR_EVENT,
        initial_target="OPS",
        initial_missing=[],
    )
    state = load_or_001()
    result = create_graph(reasoner=provider).invoke(state, config=thread_config(state["case_id"]))

    assert not result.get("__interrupt__")
    assert result["contact_policy_result"].decision is PolicyDecision.PERMITTED
    assert result["should_wait_event"] is False
    assert result.get("information_request") is None
    assert result["questions_asked"] == 0


@pytest.mark.parametrize("route", [DecisionRoute.ASK, DecisionRoute.WAIT_FOR_EVENT])
def test_staged_contact_route_without_target_does_not_interrupt(route):
    provider = FakeDecisionProvider(initial_route=route, initial_target=None)
    state = load_or_001()
    result = create_graph(reasoner=provider).invoke(state, config=thread_config(state["case_id"]))

    assert not result.get("__interrupt__")
    assert result.get("information_request") is None
    assert result["questions_asked"] == 0


@pytest.mark.parametrize("reference_location", ["decision", "assessment"])
def test_initial_decision_rejects_unsupported_evidence_reference(reference_location):
    class UnknownReferenceProvider(FakeDecisionProvider):
        def decide(self, context, evidence, *, stage, case_input=None, case_event=None):
            decision = super().decide(
                context, evidence, stage=stage,
                case_input=case_input, case_event=case_event,
            )
            if stage is DecisionStage.INITIAL:
                if reference_location == "decision":
                    return decision.model_copy(update={"evidence_refs": ["OR-001:unknown"]})
                assessment = decision.assessment.model_copy(update={"evidence_refs": ["OR-001:unknown"]})
                return decision.model_copy(update={"assessment": assessment})
            return decision

    state = load_or_001()
    with pytest.raises(ValueError, match="evidence"):
        create_graph(reasoner=UnknownReferenceProvider()).invoke(
            state, config=thread_config(state["case_id"]),
        )


def test_staged_recovery_candidate_rejected_by_policy_is_not_published():
    provider = FakeDecisionProvider(after_intent=BuyerIntent.UNKNOWN)
    graph = create_graph(reasoner=provider)
    state = load_or_001()
    config = thread_config(state["case_id"])
    assert graph.invoke(state, config=config).get("__interrupt__")
    result = graph.invoke(Command(resume={"case_event": {
        "case_id": state["case_id"], "event_type": "NO_REPLY",
        "reply_received": False, "buyer_intent": "UNKNOWN",
    }}), config=config)

    assert result["proposed_action"] is Action.STANDARD_REATTEMPT
    assert result["recovery_policy_result"].decision is not PolicyDecision.PERMITTED
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
    assert result["case_status"] in {CaseStatus.ESCALATED, CaseStatus.BLOCKED}
    assert result["final_recommendation"].executed is False


def test_positive_reply_without_requested_landmark_cannot_select_reattempt():
    provider = FakeDecisionProvider(
        initial_missing=["landmark"],
        initial_question="What landmark marks the delivery address?",
    )
    provider.after_missing = ["landmark"]
    graph = create_graph(reasoner=provider)
    state = load_or_001()
    config = thread_config(state["case_id"])

    assert graph.invoke(state, config=config).get("__interrupt__")
    assert "landmark" in graph.get_state(config).values["information_request"].question
    result = resume(graph, config, "I still want delivery, but I do not know the landmark.")

    assert result["delivery_context"].buyer_intent is BuyerIntent.WANTS
    assert result["assessment"].missing_information == ["landmark"]
    assert result["llm_decision"].proposed_action is Action.STANDARD_REATTEMPT
    assert result["proposed_action"] is Action.ESCALATE_REVIEW
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
