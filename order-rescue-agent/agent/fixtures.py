from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import BiCaseInput, CaseEvent, CaseStatus, DeliveryContext

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def _bi_records(filename: str) -> dict[str, dict[str, Any]]:
    rows = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    return {row["case_id"]: row for row in rows}


def load_bi_case(case_id: str) -> dict[str, Any]:
    """Return only current BI input; delayed events and labels are loaded separately."""
    source = _bi_records("bi_inputs.json").get(case_id)
    if source is None:
        raise KeyError(f"Unknown synthetic BI case: {case_id}")
    case = BiCaseInput.model_validate(source)
    context = DeliveryContext(
        delivery_status=case.raw_status or "UNKNOWN",
        courier_note=case.courier_note or "",
        attempt_count=case.attempt_current,
        attempt_limit=(case.attempt_current + case.attempts_remaining)
        if case.attempt_current is not None and case.attempts_remaining is not None else None,
        return_state=(case.return_state or "UNKNOWN").upper(),
        contact_eligible=not any(
            item.get("outcome") == "invalid_number" for item in case.contact_evidence
        ),
        unsupported_refusal=case.raw_status == "REFUSED" and not any(
            item.get("outcome") in {"direct_refusal", "confirmed_refusal"}
            for item in case.contact_evidence
        ),
    )
    return {
        "case_id": case.case_id,
        "trigger_event": "DELIVERY_FAILED",
        "case_input": case,
        "delivery_context": context,
        "evidence": [],
        "assessment": None,
        "missing_information": [],
        "information_request": None,
        "buyer_reply": None,
        "case_event": None,
        "questions_asked": 0,
        "proposed_action": None,
        "contact_policy_result": None,
        "recovery_policy_result": None,
        "final_recommendation": None,
        "case_status": CaseStatus.RUNNING,
        "iteration": 1,
        "should_ask_buyer": False,
        "events": [],
    }


def load_bi_event(case_id: str) -> CaseEvent | None:
    """Load one simulated event only when a caller explicitly requests the later event."""
    source = _bi_records("bi_events.json").get(case_id)
    if source is None:
        raise KeyError(f"Unknown synthetic BI case: {case_id}")
    if source.get("event_type") is None:
        return None
    return CaseEvent.model_validate(source)


def load_or_001() -> dict[str, Any]:
    """Compatibility helper; reads observable inputs from the BI workbook export."""
    return load_bi_case("OR-001")
