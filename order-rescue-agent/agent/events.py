from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .schemas import ExecutionEvent


class EventType(StrEnum):
    NODE_STARTED = "NODE_STARTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    ASSESSMENT_COMPLETED = "ASSESSMENT_COMPLETED"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"
    BUYER_REPLY_RECEIVED = "BUYER_REPLY_RECEIVED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    STATE_TRANSITION = "STATE_TRANSITION"
    RECOMMENDATION_PUBLISHED = "RECOMMENDATION_PUBLISHED"


def execution_event(
    state: dict[str, Any], node_id: str, event_type: EventType, payload: dict[str, Any] | None = None
) -> ExecutionEvent:
    case_id = state["case_id"]
    iteration = state.get("iteration", 1)
    event_id = f"{case_id}:{iteration}:{node_id}:{event_type.value}"
    return ExecutionEvent(
        event_id=event_id,
        case_id=case_id,
        iteration=iteration,
        node_id=node_id,
        event_type=event_type.value,
        timestamp=datetime.now(UTC).isoformat(),
        payload=payload or {},
    )


def lifecycle_events(state: dict[str, Any], node_id: str) -> list[ExecutionEvent]:
    return [
        execution_event(state, node_id, EventType.NODE_STARTED),
        execution_event(state, node_id, EventType.NODE_COMPLETED),
    ]
