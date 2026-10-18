from agent.policy import evaluate_contact_policy, evaluate_recovery_policy
from agent.schemas import Action, Assessment, Confidence, DeliveryContext, Hypothesis, PolicyDecision


def context(**changes):
    values = {
        "delivery_status": "RECIPIENT_UNAVAILABLE",
        "courier_note": "No answer on first attempt.",
        "attempt_count": 1,
        "attempt_limit": 3,
        "return_state": "NOT_STARTED",
        "contact_eligible": True,
        "unsupported_refusal": False,
    }
    values.update(changes)
    return DeliveryContext(**values)


def assessment(**changes):
    values = {
        "hypothesis": Hypothesis.TEMP_AVAILABILITY_CONFLICT,
        "confidence": Confidence.HIGH,
        "missing_information": [],
        "evidence_refs": ["ev-1"],
        "summary": "Buyer confirmed delivery intent.",
    }
    values.update(changes)
    return Assessment(**values)


def test_policy_blocks_unknown_action():
    result = evaluate_recovery_policy("AUTO_RETURN", context(), assessment())
    assert result.decision is PolicyDecision.BLOCKED
    assert "POL-ACTION-001" in result.triggering_rule_ids


def test_policy_blocks_retry_after_return_started():
    result = evaluate_recovery_policy(Action.STANDARD_REATTEMPT, context(return_state="STARTED"), assessment())
    assert result.decision is PolicyDecision.BLOCKED
    assert "POL-RETURN-001" in result.triggering_rule_ids


def test_policy_blocks_retry_when_attempts_exhausted():
    result = evaluate_recovery_policy(Action.STANDARD_REATTEMPT, context(attempt_count=3, attempt_limit=3), assessment())
    assert result.decision is PolicyDecision.BLOCKED
    assert "POL-ATTEMPT-001" in result.triggering_rule_ids


def test_unsupported_refusal_requires_review():
    result = evaluate_recovery_policy(
        Action.STANDARD_REATTEMPT,
        context(unsupported_refusal=True),
        assessment(hypothesis=Hypothesis.UNSUPPORTED_REFUSAL),
    )
    assert result.decision is PolicyDecision.ESCALATE
    assert "POL-REFUSAL-001" in result.triggering_rule_ids


def test_review_action_escalates_unsupported_refusal():
    result = evaluate_recovery_policy(
        Action.ESCALATE_REVIEW,
        context(unsupported_refusal=True),
        assessment(hypothesis=Hypothesis.UNSUPPORTED_REFUSAL),
    )
    assert result.decision is PolicyDecision.ESCALATE


def test_question_limit_is_enforced():
    result = evaluate_contact_policy(context(), questions_asked=1, question_limit=1)
    assert result.decision is PolicyDecision.BLOCKED
    assert "POL-CONTACT-001" in result.triggering_rule_ids
