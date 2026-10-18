from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from . import nodes
from .schemas import (
    Action,
    Assessment,
    BiCaseInput,
    BuyerIntent,
    CaseEvent,
    CaseStatus,
    Confidence,
    DeliveryContext,
    Evidence,
    ExecutionEvent,
    EventType as BiEventType,
    FinalRecommendation,
    Hypothesis,
    InformationRequest,
    PolicyDecision,
    PolicyResult,
    PolicyRule,
    ReturnState,
    RuleResult,
)
from .reasoning import Reasoner
from .state import AgentState


def _after_planning(state: AgentState) -> str:
    return "contact_policy_gate" if state.get("should_wait_event") else "propose_recovery"


def _after_contact_policy(state: AgentState) -> str:
    result = state.get("contact_policy_result")
    return "generate_question" if result and result.decision.value == "PERMITTED" else "propose_recovery"


def _after_input_validation(state: AgentState) -> str:
    return "finalize" if state.get("recovery_policy_result") is not None else "build_evidence"


def create_graph(checkpointer: InMemorySaver | None = None, *, reasoner: Reasoner | None = None):
    """Compile the single-case workflow with an in-memory checkpoint by default."""
    builder = StateGraph(AgentState)
    builder.add_node("validate_input", nodes.validate_input)
    builder.add_node("build_evidence", nodes.build_evidence)
    assessment_node = nodes.assess_case if reasoner is None else lambda state: nodes.assess_case(state, reasoner)
    builder.add_node("assess_case", assessment_node)
    builder.add_node("plan_information", nodes.plan_information)
    builder.add_node("contact_policy_gate", nodes.contact_policy_gate)
    builder.add_node("generate_question", nodes.generate_question)
    builder.add_node("wait_for_buyer", nodes.wait_for_buyer)
    builder.add_node("parse_buyer_reply", nodes.parse_buyer_reply)
    builder.add_node("propose_recovery", nodes.propose_recovery)
    builder.add_node("recovery_policy_gate", nodes.recovery_policy_gate)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges("validate_input", _after_input_validation)
    builder.add_edge("build_evidence", "assess_case")
    builder.add_edge("assess_case", "plan_information")
    builder.add_conditional_edges("plan_information", _after_planning)
    builder.add_conditional_edges("contact_policy_gate", _after_contact_policy)
    builder.add_edge("generate_question", "wait_for_buyer")
    builder.add_edge("wait_for_buyer", "parse_buyer_reply")
    builder.add_edge("parse_buyer_reply", "build_evidence")
    builder.add_edge("propose_recovery", "recovery_policy_gate")
    builder.add_edge("recovery_policy_gate", "finalize")
    builder.add_edge("finalize", END)
    checkpoint = checkpointer or InMemorySaver(
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=[
                Action,
                Assessment,
                BiCaseInput,
                BuyerIntent,
                CaseEvent,
                CaseStatus,
                Confidence,
                DeliveryContext,
                Evidence,
                ExecutionEvent,
                BiEventType,
                FinalRecommendation,
                Hypothesis,
                InformationRequest,
                PolicyDecision,
                PolicyResult,
                PolicyRule,
                ReturnState,
                RuleResult,
            ]
        )
    )
    return builder.compile(checkpointer=checkpoint)


def thread_config(case_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": case_id}}
