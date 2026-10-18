from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from langgraph.types import Command

from agent.fixtures import load_bi_case, load_bi_event, load_or_001
from agent.graph import create_graph, thread_config
from agent.reasoning import DeepSeekReasoner


def _show_assessment(assessment) -> None:
    print(f"  Hypothesis: {assessment.hypothesis.value}")
    print(f"  Confidence: {assessment.confidence.value}")
    print(f"  Missing information: {', '.join(assessment.missing_information) or 'none'}")
    print(f"  Summary: {assessment.summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one synthetic BI delivery case through LangGraph.")
    parser.add_argument("--case", default="OR-001", help="BI case ID, for example OR-001 or OR-038.")
    parser.add_argument("--auto", action="store_true", help="Resume with the synthetic reply fixture after the graph pauses.")
    parser.add_argument("--reply", help="Supply a simulated buyer reply without prompting interactively.")
    parser.add_argument("--llm", action="store_true", help="Use DeepSeek for both assessments; requires DEEPSEEK_API_KEY.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    initial = load_or_001() if args.case == "OR-001" else load_bi_case(args.case)
    reasoner = DeepSeekReasoner() if args.llm else None
    graph = create_graph(reasoner=reasoner)
    config = thread_config(initial["case_id"])

    print(f"Order Rescue — synthetic BI case {initial['case_id']}")
    print("Initial delivery evidence:")
    print(f"  Trigger: {initial['trigger_event']}")
    print(f"  Status: {initial['delivery_context'].delivery_status}")
    print(f"  Courier note: {initial['delivery_context'].courier_note}")
    print(f"\nRunning initial assessment{' with DeepSeek' if args.llm else ''}...")
    initial_result = graph.invoke(initial, config=config)
    pending = graph.get_state(config).values
    _show_assessment(pending["assessment"])
    if not initial_result.get("__interrupt__"):
        print("\nCase completed without requesting a new event.")
        print(f"Recommendation: {pending['final_recommendation'].action.value} ({pending['final_recommendation'].policy_decision.value})")
        return
    print(f"\nSimulated clarification/event request: {pending['information_request'].question}")
    print(f"Case status: {pending['case_status'].value} (checkpoint saved in memory)")

    if args.reply is not None:
        reply = args.reply
    elif args.auto:
        reply = load_bi_event(initial["case_id"])
    else:
        reply = input("Enter a simulated buyer reply: ").strip()

    if reply is None:
        print("No later event is provided for this case; the checkpoint remains waiting.")
        return
    print(f"\nSimulated buyer reply/event: {reply}")
    resume_value = {"case_event": reply.model_dump(mode="json")} if hasattr(reply, "model_dump") else {"text": reply}
    result = graph.invoke(Command(resume=resume_value), config=config)
    if result.get("__interrupt__"):
        waiting = graph.get_state(config).values
        print(f"\nThe case is waiting for another event: {waiting['information_request'].question}")
        print(f"Current candidate: {waiting['proposed_action'].value}; policy: {waiting['recovery_policy_result'].decision.value}")
        return
    print("\nUpdated evidence:")
    for item in result["evidence"]:
        print(f"  - {item.kind}: {item.value} [{item.provenance}; {item.evidence_id}]")
    print("\nReassessment:")
    _show_assessment(result["assessment"])
    print("\nRecovery policy checks:")
    policy = result["recovery_policy_result"]
    for rule in policy.rules:
        print(f"  {rule.result.value} {rule.rule_id}: {rule.reason}")
    print(f"  Decision: {policy.decision.value} ({policy.policy_version})")

    recommendation = result.get("final_recommendation")
    if recommendation is None:
        print("\nThe workflow has not published a final recommendation yet.")
        return
    print("\nFinal recommendation:")
    print(f"  Action: {recommendation.action.value}")
    print(f"  Policy decision: {recommendation.policy_decision.value}")
    print(f"  Rationale: {recommendation.rationale}")
    print("  Executed: no")
    print("\nExecution history:")
    for event in result["events"]:
        print(f"  iter {event.iteration} · {event.event_type} · {event.node_id}")


if __name__ == "__main__":
    main()
