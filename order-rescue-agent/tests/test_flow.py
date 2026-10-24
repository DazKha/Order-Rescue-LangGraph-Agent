import pytest

from langgraph.types import Command

from agent.events import EventType
from agent.fixtures import load_bi_event, load_or_001
from agent.graph import create_graph, thread_config
from agent.nodes import assess_case
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


def resume(graph, config, reply="Yesterday I was at work and missed the call. I still want delivery."):
    return graph.invoke(Command(resume={"text": reply}), config=config)


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
    assert any(item.raw_text == event.event_text for item in result["evidence"])
    assert result["proposed_action"] is Action.STANDARD_REATTEMPT
    assert result["recovery_policy_result"] is not None
    assert result["case_status"] is CaseStatus.COMPLETED


def test_resumed_event_revalidates_before_rebuilding_evidence_and_reassessing():
    provider = FakeDecisionProvider()
    state = load_or_001()
    graph = create_graph(reasoner=provider)
    config = thread_config(state["case_id"])
    assert graph.invoke(state, config=config).get("__interrupt__")

    event = load_bi_event("OR-001")
    result = graph.invoke(Command(resume={"case_event": event.model_dump(mode="json")}), config=config)
    started = [item.node_id for item in result["events"] if item.event_type == EventType.NODE_STARTED]

    assert started.count("validate_input") == 2
    assert started.index("validate_input", 1) < started.index("build_evidence", 2)
    assert [stage for stage, _, _ in provider.calls] == [DecisionStage.INITIAL, DecisionStage.AFTER_EVENT]


def test_eligible_run_requires_configured_llm_and_preflight_does_not(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    state = load_or_001()
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        create_graph().invoke(state, config=thread_config(state["case_id"]))

    from agent.fixtures import load_bi_case
    blocked = load_bi_case("OR-055")
    result = create_graph().invoke(blocked, config=thread_config(blocked["case_id"]))
    assert result["final_recommendation"].action is Action.NO_ACTION


def test_ineligible_lifecycle_on_resume_stops_before_second_llm_call():
    from agent.schemas import BiCaseInput

    provider = FakeDecisionProvider()
    initial = load_or_001()
    graph = create_graph(reasoner=provider)
    config = thread_config(initial["case_id"])
    assert graph.invoke(initial, config=config).get("__interrupt__")

    changed = graph.get_state(config).values["case_input"].model_dump(mode="json")
    changed["return_state"] = "started"
    graph.update_state(config, {"case_input": BiCaseInput.model_validate(changed)})
    event = load_bi_event("OR-001")
    result = graph.invoke(Command(resume={"case_event": event.model_dump(mode="json")}), config=config)

    assert len(provider.calls) == 1
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
    assert result["eligibility"] == "INELIGIBLE"


def test_event_for_another_case_is_blocked_before_reassessment():
    provider = FakeDecisionProvider()
    initial = load_or_001()
    graph = create_graph(reasoner=provider)
    config = thread_config(initial["case_id"])
    assert graph.invoke(initial, config=config).get("__interrupt__")

    result = graph.invoke(Command(resume={"case_event": {
        "case_id": "OR-OTHER", "event_type": "BUYER_REPLY",
        "event_text": "Vẫn muốn nhận", "reply_received": True,
    }}), config=config)

    assert len(provider.calls) == 1
    assert result["final_recommendation"].action is Action.ESCALATE_REVIEW
    assert result["recovery_policy_result"].decision is PolicyDecision.BLOCKED


def test_llm_ask_with_natural_language_missing_information_pauses_for_buyer():
    provider = FakeDecisionProvider(
        initial_missing=[
            "Buyer's preferred delivery time or alternate address",
            "Whether buyer wants redelivery or another resolution",
        ],
        initial_question="Bạn còn muốn nhận đơn hàng này không?",
    )
    graph = create_graph(reasoner=provider)
    initial = load_or_001()
    config = thread_config(initial["case_id"])

    result = graph.invoke(initial, config=config)
    waiting = graph.get_state(config).values

    assert result.get("__interrupt__")
    assert waiting["case_status"] is CaseStatus.WAITING_FOR_BUYER
    assert waiting["information_request"].question == "Bạn còn muốn nhận đơn hàng này không?"
    assert waiting["final_recommendation"] is None


def test_waiting_for_buyer_has_no_recovery_proposal_or_final_policy_result():
    provider = FakeDecisionProvider()
    state = load_or_001()
    graph = create_graph(reasoner=provider)
    config = thread_config(state["case_id"])

    assert graph.invoke(state, config=config).get("__interrupt__")
    waiting = graph.get_state(config).values

    assert waiting["proposed_action"] is None
    assert waiting["recovery_policy_result"] is None
    assert waiting["final_recommendation"] is None


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
