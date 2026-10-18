from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from langgraph.types import Command

from agent.fixtures import FIXTURE_DIR, load_or_001
from agent.graph import create_graph, thread_config
from agent.reasoning import DeepSeekReasoner


def _show_assessment(assessment) -> None:
    print(f"  Hypothesis: {assessment.hypothesis.value}")
    print(f"  Confidence: {assessment.confidence.value}")
    print(f"  Missing information: {', '.join(assessment.missing_information) or 'none'}")
    print(f"  Summary: {assessment.summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic OR-001 LangGraph workflow.")
    parser.add_argument("--auto", action="store_true", help="Resume with the synthetic reply fixture after the graph pauses.")
    parser.add_argument("--reply", help="Supply a simulated buyer reply without prompting interactively.")
    parser.add_argument("--llm", action="store_true", help="Use DeepSeek for both assessments; requires DEEPSEEK_API_KEY.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    initial = load_or_001()
    reasoner = DeepSeekReasoner() if args.llm else None
    graph = create_graph(reasoner=reasoner)
    config = thread_config(initial["case_id"])

    print("Order Rescue V0 — synthetic case OR-001")
    print("Initial delivery evidence:")
    print(f"  Trigger: {initial['trigger_event']}")
    print(f"  Status: {initial['delivery_context'].delivery_status}")
    print(f"  Courier note: {initial['delivery_context'].courier_note}")
    print(f"\nRunning initial assessment{' with DeepSeek' if args.llm else ''}...")
    graph.invoke(initial, config=config)
    pending = graph.get_state(config).values
    _show_assessment(pending["assessment"])
    print(f"\nSimulated buyer question: {pending['information_request'].question}")
    print("Case status: WAITING_FOR_BUYER (graph checkpoint saved in memory)")

    if args.reply is not None:
        reply = args.reply
    elif args.auto:
        reply = json.loads((FIXTURE_DIR / "or_001_reply.json").read_text(encoding="utf-8"))["reply"]
    else:
        reply = input("Enter a simulated buyer reply: ").strip()

    print(f"\nSimulated buyer reply: {reply}")
    result = graph.invoke(Command(resume={"text": reply}), config=config)
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

    recommendation = result["final_recommendation"]
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
