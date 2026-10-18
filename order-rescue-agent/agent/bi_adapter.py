from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .schemas import BiCaseInput


RAW_STATUSES = frozenset({
    "RECIPIENT_UNAVAILABLE",
    "CONTACT_FAILED",
    "REFUSED",
    "ADDRESS_ISSUE",
    "RESCHEDULED_BY_BUYER",
    "CANCELLED_IN_TRANSIT",
    "DELIVERY_FAILED_OTHER",
})
ENUM_VALUES = {
    "test_type": frozenset({"golden", "edge", "safety"}),
    "service_type": frozenset({"SPX_STANDARD", "SPX_EXPRESS"}),
    "area_type": frozenset({"urban", "suburban", "remote"}),
    "payment_type": frozenset({"PREPAID", "COD"}),
    "return_state": frozenset({"not_started", "started", "completed", "unknown"}),
    "address_issue": frozenset({"present", "absent", "unknown"}),
    "actor_role": frozenset({"OPS_REVIEWER", "SELLER", "BUYER"}),
}
REQUIRED_FIELDS = ("case_id", "failed_at", "assessed_at", "raw_status", "policy_version")
TIME_FIELDS = ("failed_at", "assessed_at", "return_started_at", "decision_deadline")


@dataclass(frozen=True)
class InputValidationResult:
    case: BiCaseInput | None
    issues: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return self.case is not None and not self.issues


def validate_case_input(raw: dict[str, Any]) -> InputValidationResult:
    """Validate BI input structure and required enums without reading expected labels."""
    issues: set[str] = set()
    try:
        case = BiCaseInput.model_validate(raw)
    except ValidationError as exc:
        issues.update(str(error["loc"][0]) for error in exc.errors(include_input=False) if error["loc"])
        return InputValidationResult(case=None, issues=tuple(sorted(issues)))

    for field in REQUIRED_FIELDS:
        if getattr(case, field) is None or not str(getattr(case, field)).strip():
            issues.add(field)

    if case.raw_status is not None and case.raw_status not in RAW_STATUSES:
        issues.add("raw_status")
    for field, allowed in ENUM_VALUES.items():
        value = getattr(case, field)
        if value is not None and value not in allowed:
            issues.add(field)

    for field in TIME_FIELDS:
        value = getattr(case, field)
        if value is None or not str(value).strip():
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            issues.add(field)
            continue
        if parsed.tzinfo is None:
            issues.add(field)

    return InputValidationResult(case=case, issues=tuple(sorted(issues)))
