from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import CaseStatus, DeliveryContext

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def load_or_001() -> dict[str, Any]:
    """Load observable OR-001 inputs only; no expected action is included."""
    source = json.loads((FIXTURE_DIR / "or_001.json").read_text(encoding="utf-8"))
    return {
        "case_id": source["case_id"],
        "trigger_event": source["trigger_event"],
        "delivery_context": DeliveryContext.model_validate(source["delivery_context"]),
        "evidence": [],
        "assessment": None,
        "missing_information": [],
        "information_request": None,
        "buyer_reply": None,
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
