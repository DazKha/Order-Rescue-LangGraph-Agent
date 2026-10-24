from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pydantic import ValidationError

from .prompts import assessment_system_prompt, decision_system_prompt
from .schemas import (
    AgentDecision,
    Assessment,
    BiCaseInput,
    BuyerIntent,
    CaseEvent,
    Confidence,
    DecisionRoute,
    DecisionStage,
    DecisionTarget,
    DeliveryContext,
    Evidence,
    EventType,
    Hypothesis,
)


class DecisionReasoner(Protocol):
    """Provider for a structured decision at one bounded workflow stage."""

    def decide(
        self,
        context: DeliveryContext,
        evidence: list[Evidence],
        *,
        stage: DecisionStage,
        case_input: BiCaseInput | None = None,
        case_event: CaseEvent | None = None,
    ) -> AgentDecision: ...


def _post_json(url: str, *, headers: dict[str, str], body: bytes, timeout: float) -> dict[str, Any]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"DeepSeek request failed with HTTP {exc.code}.") from None
    except URLError as exc:
        reason = getattr(exc, "reason", "connection error")
        raise RuntimeError(f"DeepSeek request failed: {reason}.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("DeepSeek returned an invalid JSON response.") from None


class DeepSeekReasoner:
    """Structured assessment using DeepSeek's chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        timeout: float = 30,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("Set DEEPSEEK_API_KEY to enable DeepSeek reasoning.")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        self.timeout = timeout
        self.transport = transport or _post_json

    def decide(
        self,
        context: DeliveryContext,
        evidence: list[Evidence],
        *,
        stage: DecisionStage,
        case_input: BiCaseInput | None = None,
        case_event: CaseEvent | None = None,
    ) -> AgentDecision:
        """Return a validated model proposal; policy gates remain separate."""
        if stage not in (DecisionStage.INITIAL, DecisionStage.AFTER_EVENT):
            raise RuntimeError("Invalid decision stage.")
        if stage is DecisionStage.AFTER_EVENT and case_event is None:
            raise RuntimeError("DeepSeek after-event decision requires a case event.")
        observed_inputs = {
            "stage": stage.value,
            "delivery_context": context.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        if case_input is not None:
            observed_inputs["case_input"] = case_input.model_dump(mode="json")
        if stage is DecisionStage.AFTER_EVENT:
            observed_inputs["case_event"] = case_event.model_dump(mode="json")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": (
                    decision_system_prompt(stage)
                )},
                {"role": "user", "content": json.dumps(observed_inputs, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 1024,
            "stream": False,
        }
        try:
            response = self.transport(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self.timeout,
            )
            choice = response["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("incomplete response")
            raw = json.loads(choice["message"]["content"])
            decision = AgentDecision.model_validate(raw)
        except Exception:
            raise RuntimeError("DeepSeek decision request or response failed validation.") from None

        if decision.stage is not stage:
            raise RuntimeError("DeepSeek decision stage did not match the request.")
        known_ids = {item.evidence_id for item in evidence}
        if not set(decision.assessment.evidence_refs).issubset(known_ids) or not set(decision.evidence_refs).issubset(known_ids):
            raise RuntimeError("DeepSeek decision referenced evidence that was not provided.")
        if stage is DecisionStage.INITIAL:
            if decision.route is DecisionRoute.ASK:
                request = decision.information_request
                if decision.target is not DecisionTarget.BUYER or request is None or not request.question.strip() or not request.purpose.strip():
                    raise RuntimeError("DeepSeek ASK decision requires a simulated buyer question.")
            elif decision.route is DecisionRoute.WAIT_FOR_EVENT:
                raise RuntimeError("DeepSeek cannot request a non-buyer wait in this flow.")
            elif decision.proposed_action is None or not (decision.rationale or "").strip():
                raise RuntimeError("DeepSeek recovery decision is missing an action or rationale.")
        elif (
            decision.route is not DecisionRoute.PROPOSE_RECOVERY
            or not isinstance(raw, dict)
            or "buyer_intent" not in raw
            or "parsed_facts" not in raw
            or decision.buyer_intent is None
            or not decision.parsed_facts
            or any(not key.strip() or not value.strip() for key, value in decision.parsed_facts.items())
            or decision.proposed_action is None
            or not (decision.rationale or "").strip()
        ):
            raise RuntimeError("DeepSeek after-event decision is missing required extraction or action.")
        if stage is DecisionStage.AFTER_EVENT:
            observed_intent = case_event.buyer_intent
            if case_event.event_type not in {EventType.BUYER_REPLY, EventType.BUYER_REPLY_LATE} and decision.buyer_intent is not BuyerIntent.UNKNOWN:
                raise RuntimeError("DeepSeek decision inferred buyer intent from a non-buyer event.")
            no_reply = case_event.event_type in {EventType.NO_REPLY, EventType.TIMEOUT} or case_event.reply_received is False
            if (no_reply or observed_intent is BuyerIntent.UNKNOWN) and decision.buyer_intent is not BuyerIntent.UNKNOWN:
                raise RuntimeError("DeepSeek decision inferred buyer intent without supporting event evidence.")
            if observed_intent not in (None, BuyerIntent.UNKNOWN) and decision.buyer_intent not in (observed_intent, BuyerIntent.UNKNOWN):
                raise RuntimeError("DeepSeek decision buyer intent conflicts with the case event.")
        if decision.route is DecisionRoute.PROPOSE_RECOVERY:
            # These fields only have meaning on ASK. A model may include them
            # despite selecting PROPOSE_RECOVERY; they must not look like a
            # second buyer question after the one-question limit.
            decision = decision.model_copy(update={"target": None, "information_request": None})
        return decision

    def assess(
        self, context: DeliveryContext, evidence: list[Evidence], *, case_input: BiCaseInput | None = None
    ) -> Assessment:
        observed_inputs = {
            "delivery_context": context.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        if case_input is not None:
            observed_inputs["case_input"] = case_input.model_dump(mode="json")
        system_prompt = assessment_system_prompt()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(observed_inputs, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 512,
            "stream": False,
        }
        response = self.transport(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.timeout,
        )
        try:
            choice = response["choices"][0]
            finish_reason = choice.get("finish_reason")
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("DeepSeek returned an invalid response shape.") from None
        if finish_reason != "stop":
            raise RuntimeError(f"DeepSeek did not complete the structured assessment (finish_reason={finish_reason}).")
        try:
            assessment = Assessment.model_validate_json(content)
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(str(part) for part in error["loc"]) or "response"
                for error in exc.errors(include_input=False)
            )
            try:
                response_keys = sorted(json.loads(content).keys())
            except (json.JSONDecodeError, AttributeError):
                response_keys = []
            raise RuntimeError(
                f"DeepSeek structured assessment failed schema validation at: {fields}; "
                f"top-level keys returned: {response_keys}."
            ) from None

        known_ids = {item.evidence_id for item in evidence}
        if not set(assessment.evidence_refs).issubset(known_ids):
            raise RuntimeError("DeepSeek assessment referenced evidence that was not provided.")

        # A model may repeat an already-resolved evidence gap. Keep this
        # confidence update tied to structured buyer evidence, never to a
        # target action or expected label.
        if context.buyer_intent is BuyerIntent.WANTS_DELIVERY:
            remaining_missing = [
                item for item in assessment.missing_information if item != "buyer_intent"
            ]
            if (
                assessment.hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT
                and not remaining_missing
            ):
                assessment = assessment.model_copy(update={
                    "confidence": Confidence.HIGH,
                    "missing_information": remaining_missing,
                })
        return assessment
