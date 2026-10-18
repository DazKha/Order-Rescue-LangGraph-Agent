from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .schemas import (
    Action,
    Assessment,
    BiCaseInput,
    BuyerIntent,
    CaseEvent,
    DeliveryContext,
    Eligibility,
    EventType,
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


def evaluate_bi_contact_policy(
    case: BiCaseInput, *, questions_asked: int, question_limit: int = 1, target: str = "BUYER",
    contact_verified: bool = False,
) -> PolicyResult:
    """Evaluate the BI contact rules for a simulated, role-appropriate question."""
    rules: list[PolicyRule] = []
    _append_rule(rules, "R12", questions_asked < question_limit,
                 "At most one simulated clarification is allowed per case.")
    invalid_channel = any(item.get("outcome") == "invalid_number" for item in case.contact_evidence)
    target_allowed = target == "OPS" or target == "SELLER" or (target == "BUYER" and (not invalid_channel or contact_verified))
    _append_rule(rules, "R22", target_allowed,
                 "A valid contact channel exists for the selected actor." if target_allowed else
                 "Buyer contact is invalid; use an authorized seller or Ops path.")
    failed = [rule.rule_id for rule in rules if rule.result is RuleResult.FAIL]
    decision = PolicyDecision.PERMITTED if not failed else PolicyDecision.ESCALATED
    return PolicyResult(decision=decision, policy_version=case.policy_version or POLICY_VERSION,
                        rules=rules, triggering_rule_ids=failed)


def evaluate_bi_eligibility(case: BiCaseInput) -> Eligibility:
    if case.return_state in {"started", "completed"} or case.attempts_remaining == 0 or case.raw_status == "CANCELLED_IN_TRANSIT":
        return Eligibility.INELIGIBLE
    if case.return_state in {None, "unknown"} or not case.decision_deadline:
        return Eligibility.UNKNOWN
    try:
        deadline = datetime.fromisoformat(case.decision_deadline.replace("Z", "+00:00"))
        assessed = datetime.fromisoformat((case.assessed_at or "").replace("Z", "+00:00"))
    except ValueError:
        return Eligibility.UNKNOWN
    if deadline <= assessed:
        return Eligibility.INELIGIBLE
    return Eligibility.ELIGIBLE


def evaluate_bi_recovery_policy(
    action: Action | str,
    case: BiCaseInput,
    assessment: Assessment,
    *,
    buyer_intent: BuyerIntent = BuyerIntent.UNKNOWN,
    event: CaseEvent | dict[str, Any] | None = None,
) -> PolicyResult:
    """Apply deterministic BI R01-R22 checks to a candidate action."""
    try:
        candidate = Action(action)
    except (ValueError, TypeError):
        candidate = None
    event_data = event.model_dump(mode="json") if isinstance(event, CaseEvent) else (event or {})
    event_text = str(event_data.get("event_text") or "")
    lowered = f"{event_text} {case.raw_reason or ''} {case.courier_note or ''}".lower()
    extra = case.extra_context
    rules: list[PolicyRule] = []

    _append_rule(rules, "POL-ACTION-001", candidate is not None,
                 "Candidate is in the BI action whitelist." if candidate else "Unknown action is outside the BI whitelist.")
    if extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"}:
        _append_rule(rules, "R20", False, "Stale or duplicate event cannot create a new decision.")
        return _policy_result(case, rules, forced=PolicyDecision.BLOCKED)
    if extra.get("pii_detected"):
        _append_rule(rules, "R15", False, "PII-bearing record must be dropped before processing.")
        _append_rule(rules, "R16", False, "Invalid/sensitive input fails closed.")
        return _policy_result(case, rules, forced=PolicyDecision.BLOCKED)
    if assessment.hypothesis is Hypothesis.SECURITY_INPUT_ANOMALY:
        _append_rule(rules, "R19", False, "Instruction-like case text is untrusted data and requires review.")
        return _policy_result(case, rules, forced=PolicyDecision.ESCALATED)
    if assessment.hypothesis is Hypothesis.DATA_QUALITY_INVALID:
        _append_rule(rules, "R16", False, "Invalid input fails closed for Ops correction.")
        return _policy_result(case, rules, forced=PolicyDecision.BLOCKED)

    if candidate is Action.STANDARD_REATTEMPT:
        return_state = case.return_state
        if return_state in {"started", "completed"}:
            _append_rule(rules, "R01", False, "Return lifecycle is already started or completed.")
        elif return_state in {None, "unknown"}:
            _append_rule(rules, "R02", False, "Unknown return state requires Ops verification.")
        else:
            _append_rule(rules, "R01", True, "Return lifecycle has not started.")

        deadline_state = _deadline_state(case)
        availability_after_deadline = any(token in lowered for token in ("thứ hai tuần sau", "monday next week", "sau hạn xử lý"))
        if availability_after_deadline:
            _append_rule(rules, "R03", False, "Buyer availability is after the recorded decision deadline.")
        elif deadline_state == "unknown":
            _append_rule(rules, "R02", False, "Unknown decision deadline requires Ops verification.")
        elif deadline_state == "expired":
            _append_rule(rules, "R03", False, "Decision deadline has passed.")
        else:
            _append_rule(rules, "R03", True, "Decision deadline remains open.")

        if case.attempts_remaining == 0:
            _append_rule(rules, "R04", False, "No standard delivery attempts remain.")
        elif case.attempts_remaining is None:
            _append_rule(rules, "R04", False, "Attempt eligibility is unknown.")
        else:
            _append_rule(rules, "R04", True, "At least one standard delivery attempt remains.")

    address_change = any(token in event_text.lower() for token in ("địa chỉ mới", "địa chỉ khác", "đổi địa chỉ", "chuyển nhà", "new address", "change address"))
    cod_change = any(token in lowered for token in ("đổi cách thanh toán", "chuyển khoản thay vì", "change payment", "cod to"))
    exact_time = bool(re.search(r"\b\d{1,2}:\d{2}\b", event_text)) and any(
        token in lowered for token in ("giao đúng", "đúng giờ", "exact time", "at ")
    )
    _append_rule(rules, "R06", not address_change,
                 "No address change is requested." if not address_change else "Address changes are outside agent authority.")
    _append_rule(rules, "R07", not cod_change,
                 "No COD/payment change is requested." if not cod_change else "COD/payment changes are outside agent authority.")
    _append_rule(rules, "R11", not exact_time and buyer_intent is not BuyerIntent.CONDITIONAL,
                 "No exact delivery-time promise is needed." if not exact_time else "Exact delivery time is conditional and cannot be promised.")

    unsupported_refusal = case.raw_status == "REFUSED" and assessment.hypothesis in {
        Hypothesis.REFUSAL_UNSUPPORTED, Hypothesis.REFUSAL_CONFIRMED,
    }
    _append_rule(rules, "R08", not unsupported_refusal,
                 "Refusal evidence does not require an automatic outcome." if not unsupported_refusal else
                 "Refusal evidence requires human review.")
    conflict = assessment.hypothesis is Hypothesis.RECORD_CONFLICT or "không có cuộc gọi" in lowered
    _append_rule(rules, "R09", not conflict,
                 "No material evidence conflict is detected." if not conflict else "Conflicting evidence requires human review.")

    signal = case.disruption_signal
    verified_disruption = bool(signal.get("flag") and signal.get("verified") and signal.get("source"))
    route = case.extra_context.get("parcel_route")
    signal_scope = signal.get("scope")
    scope_matches = bool(signal_scope and (route is None or route in signal_scope or signal_scope.endswith("ALL")))
    if candidate is Action.HOLD_DISRUPTION:
        disruption_allowed = verified_disruption and scope_matches
        reason = "Disruption source is verified and scope matches." if disruption_allowed else "Disruption is unsourced, unverified, or does not match this parcel route."
    else:
        disruption_allowed = True
        reason = "No disruption hold was proposed; this rule does not block the current candidate."
    _append_rule(rules, "R10", disruption_allowed, reason)

    damage = bool(extra.get("damage_flag")) or any(item.get("outcome") == "parcel_damaged" for item in case.contact_evidence)
    _append_rule(rules, "R18", not damage,
                 "No parcel-damage evidence is present." if not damage else "Parcel damage requires Ops review.")
    refund_request = any(token in lowered for token in ("hoàn tiền", "refund", "duyệt hoàn"))
    _append_rule(rules, "R17", not refund_request,
                 "No refund/return decision is requested." if not refund_request else "Refund/return decisions require an authorized human.")

    seller_authorized = case.actor_role != "SELLER" or (
        bool(extra.get("policy_allows_seller_confirm"))
        and (
            candidate is Action.CLARIFY
            or event_data.get("event_type") == EventType.SELLER_REPLY.value and buyer_intent is BuyerIntent.WANTS
        )
    )
    _append_rule(rules, "R21", seller_authorized,
                 "Actor authority is valid under the simulated policy." if seller_authorized else
                 "Seller confirmation authority is missing or not evidenced.")
    contact_outcome = {item.get("outcome") for item in case.contact_evidence}
    contact_valid = event_data.get("event_type") == EventType.SELLER_UPDATE.value or not ("invalid_number" in contact_outcome and event_data.get("event_type") in {
        EventType.BUYER_REPLY.value, EventType.BUYER_REPLY_LATE.value,
    })
    _append_rule(rules, "R22", contact_valid,
                 "Contact evidence supports the selected communication path." if contact_valid else
                 "Invalid buyer contact requires an authorized seller/Ops path.")
    _append_rule(rules, "R12", True, "At most one simulated contact question is allowed.")
    _append_rule(rules, "R14", True, "Buyer history is not used as an automatic denial signal.")
    _append_rule(rules, "R16", True, "Input passed required-field and vocabulary validation.")

    if candidate is Action.STANDARD_REATTEMPT:
        _append_rule(rules, "R05", buyer_intent is BuyerIntent.WANTS and not address_change and not cod_change and not damage,
                     "Direct WANTS evidence and no unresolved blockers." if buyer_intent is BuyerIntent.WANTS and not address_change and not cod_change and not damage else
                     "Reattempt needs direct WANTS evidence and no unresolved address/COD/damage conflict.")
    else:
        _append_rule(rules, "R05", True, "This recommendation does not propose a standard reattempt.")

    if candidate is Action.CLARIFY and case.attempts_remaining == 0:
        _append_rule(rules, "R04", False, "No standard delivery attempts remain; clarification cannot reopen retry eligibility.")

    if candidate is Action.ESCALATE_REVIEW:
        if case.return_state in {"started", "completed"} or assessment.hypothesis is Hypothesis.LIFECYCLE_CLOSED:
            _append_rule(rules, "R01", False, "Return lifecycle is closed; a standard recovery is blocked pending Ops review.")
        if case.attempts_remaining == 0:
            _append_rule(rules, "R04", False, "No standard delivery attempts remain.")
        if _deadline_state(case) == "expired" or any(token in lowered for token in ("thứ hai tuần sau", "monday next week", "sau hạn xử lý")):
            _append_rule(rules, "R03", False, "Decision deadline or requested availability is outside the permitted window.")
        if case.raw_status == "CANCELLED_IN_TRANSIT":
            _append_rule(rules, "R08", False, "Platform cancellation blocks delivery recovery.")
        hard_failures = {rule.rule_id for rule in rules if rule.result is RuleResult.FAIL}.intersection(
            {"R01", "R06", "R07", "R15", "R16", "R17", "R20"}
        )
        if case.raw_status == "CANCELLED_IN_TRANSIT":
            hard_failures.add("R08")
        return _policy_result(
            case, rules,
            forced=PolicyDecision.BLOCKED if hard_failures else PolicyDecision.ESCALATED,
        )

    failures = {rule.rule_id for rule in rules if rule.result is RuleResult.FAIL}
    availability_after_deadline = any(token in lowered for token in ("thứ hai tuần sau", "monday next week", "sau hạn xử lý"))
    blocked = failures.intersection({"POL-ACTION-001", "R01", "R04", "R06", "R07", "R15", "R16", "R20"})
    if "R03" in failures and not availability_after_deadline:
        blocked.add("R03")
    if blocked:
        return _policy_result(case, rules, forced=PolicyDecision.BLOCKED)
    if failures:
        return _policy_result(case, rules, forced=PolicyDecision.ESCALATED)
    return _policy_result(case, rules, forced=PolicyDecision.PERMITTED)


def _deadline_state(case: BiCaseInput) -> str:
    if not case.decision_deadline or not case.assessed_at:
        return "unknown"
    try:
        deadline = datetime.fromisoformat(case.decision_deadline.replace("Z", "+00:00"))
        assessed = datetime.fromisoformat(case.assessed_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    return "expired" if deadline <= assessed else "open"


def _append_rule(rules: list[PolicyRule], rule_id: str, passes: bool, reason: str) -> None:
    rules.append(PolicyRule(
        rule_id=rule_id,
        result=RuleResult.PASS if passes else RuleResult.FAIL,
        reason=reason,
    ))


def _policy_result(case: BiCaseInput, rules: list[PolicyRule], *, forced: PolicyDecision) -> PolicyResult:
    failures = [rule.rule_id for rule in rules if rule.result is RuleResult.FAIL]
    return PolicyResult(
        decision=forced,
        policy_version=case.policy_version or POLICY_VERSION,
        rules=rules,
        triggering_rule_ids=failures,
    )
