import json
from pathlib import Path

import pytest

from agent.policy import evaluate_bi_recovery_policy
from agent.schemas import Action, Assessment, BiCaseInput, BuyerIntent, Confidence, Hypothesis


DATA = Path(__file__).resolve().parents[1] / "data"

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
