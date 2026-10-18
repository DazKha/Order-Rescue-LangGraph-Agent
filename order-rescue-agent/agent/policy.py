from __future__ import annotations

from .schemas import (
    Action,
    Assessment,
    DeliveryContext,
    Hypothesis,
    PolicyDecision,
    PolicyResult,
    PolicyRule,
    RuleResult,
)

POLICY_VERSION = "DEMO-POLICY-0.1"


def _rule(rule_id: str, passes: bool, passed: str, failed: str) -> PolicyRule:
    return PolicyRule(rule_id=rule_id, result=RuleResult.PASS if passes else RuleResult.FAIL, reason=passed if passes else failed)


def evaluate_contact_policy(
    context: DeliveryContext, *, questions_asked: int, question_limit: int = 1
) -> PolicyResult:
    rules = [
        _rule(
            "POL-CONTACT-001",
            questions_asked < question_limit,
            "Clarification limit has not been reached.",
            "The V0 limit of one buyer clarification question per case has been reached.",
        ),
        _rule(
            "POL-CONTACT-002",
            context.contact_eligible is True and context.return_state is not None and context.return_state.value == "NOT_STARTED",
            "Case is eligible for simulated buyer clarification.",
            "Contact eligibility is unknown or the return lifecycle has started.",
        ),
    ]
    failures = [rule.rule_id for rule in rules if rule.result is RuleResult.FAIL]
    return PolicyResult(
        decision=PolicyDecision.BLOCKED if failures else PolicyDecision.PERMITTED,
        policy_version=POLICY_VERSION,
        rules=rules,
        triggering_rule_ids=failures,
    )


def evaluate_recovery_policy(
    action: Action | str, context: DeliveryContext, assessment: Assessment
) -> PolicyResult:
    try:
        candidate = Action(action)
        known_action = True
    except ValueError:
        candidate = None
        known_action = False

    rules = [
        _rule(
            "POL-ACTION-001",
            known_action,
            "Candidate uses the registered V0 action vocabulary.",
            "Unknown actions are blocked by the V0 action allowlist.",
        )
    ]
    if candidate is Action.STANDARD_REATTEMPT:
        valid_return_state = context.return_state is not None and context.return_state.value == "NOT_STARTED"
        rules.append(_rule(
            "POL-RETURN-001", valid_return_state,
            "No return lifecycle has started.",
            "A standard reattempt is blocked after a return has started or completed, or when return state is unknown.",
        ))
        attempts_known = context.attempt_count is not None and context.attempt_limit is not None
        attempts_remaining = attempts_known and context.attempt_count < context.attempt_limit
        rules.append(_rule(
            "POL-ATTEMPT-001", attempts_remaining,
            "At least one retry remains under the illustrative demo limit.",
            "Retry eligibility is unknown or the illustrative attempt limit has been reached.",
        ))
    refusal_unsupported = context.unsupported_refusal or assessment.hypothesis is Hypothesis.UNSUPPORTED_REFUSAL
    refusal_safe = not refusal_unsupported or candidate is Action.ESCALATE_REVIEW
    rules.append(_rule(
        "POL-REFUSAL-001", refusal_safe,
        "No unsupported refusal is being used to justify an automatic outcome.",
        "Unsupported refusal evidence requires human review; automatic recovery is not permitted.",
    ))

    failures = [rule.rule_id for rule in rules if rule.result is RuleResult.FAIL]
    if not known_action or "POL-RETURN-001" in failures or "POL-ATTEMPT-001" in failures:
        decision = PolicyDecision.BLOCKED
    elif refusal_unsupported and candidate is Action.ESCALATE_REVIEW:
        decision = PolicyDecision.ESCALATE
    elif "POL-REFUSAL-001" in failures:
        decision = PolicyDecision.ESCALATE
    else:
        decision = PolicyDecision.PERMITTED
    return PolicyResult(decision=decision, policy_version=POLICY_VERSION, rules=rules, triggering_rule_ids=failures)
