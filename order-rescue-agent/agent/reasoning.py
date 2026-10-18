from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pydantic import ValidationError

from .schemas import (
    Assessment,
    BuyerIntent,
    Confidence,
    DeliveryContext,
    Evidence,
    Hypothesis,
)


class Reasoner(Protocol):
    """Replaceable interface for deterministic V0 or future structured model reasoning."""

    def assess(self, context: DeliveryContext, evidence: list[Evidence]) -> Assessment: ...


class DeterministicMockReasoner:
    def assess(self, context: DeliveryContext, evidence: list[Evidence]) -> Assessment:
        refs = [item.evidence_id for item in evidence]
        status = context.delivery_status.upper()
        if context.buyer_intent is BuyerIntent.WANTS_DELIVERY:
            return Assessment(
                hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
                confidence=Confidence.HIGH,
                missing_information=[],
                evidence_refs=refs,
                summary="Buyer confirmed delivery intent; the earlier unavailable status is consistent with a temporary availability conflict.",
            )
        if "DISRUPTION" in status or "DELAYED" in status:
            return Assessment(
                hypothesis=Hypothesis.SERVICE_DISRUPTION,
                confidence=Confidence.MEDIUM,
                missing_information=[],
                evidence_refs=refs,
                summary="Available delivery context indicates a service disruption; wait for service recovery information.",
            )
        if context.unsupported_refusal or status == "REFUSED":
            return Assessment(
                hypothesis=Hypothesis.UNSUPPORTED_REFUSAL,
                confidence=Confidence.LOW,
                missing_information=["refusal_evidence"],
                evidence_refs=refs,
                summary="A refusal status lacks corroborating evidence, so buyer intent remains unknown.",
            )
        if "ADDRESS" in status:
            return Assessment(
                hypothesis=Hypothesis.UNCLEAR_ADDRESS,
                confidence=Confidence.MEDIUM,
                missing_information=["address_landmark"],
                evidence_refs=refs,
                summary="The address failure suggests that a landmark is missing; shipment address changes are outside agent authority.",
            )
        if "UNAVAILABLE" in status:
            return Assessment(
                hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
                confidence=Confidence.MEDIUM,
                missing_information=["buyer_intent"],
                evidence_refs=refs,
                summary="A no-answer delivery event is consistent with temporary unavailability, but buyer intent is not yet known.",
            )
        return Assessment(
            hypothesis=Hypothesis.UNKNOWN,
            confidence=Confidence.LOW,
            missing_information=["failure_context"],
            evidence_refs=refs,
            summary="The available evidence is insufficient to identify a supported recovery path.",
        )


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

    def assess(self, context: DeliveryContext, evidence: list[Evidence]) -> Assessment:
        observed_inputs = {
            "delivery_context": context.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        system_prompt = (
            "Assess this synthetic failed-delivery case using only the observable delivery context and evidence. "
            "Return one JSON object with exactly these fields: hypothesis, confidence, missing_information, "
            "evidence_refs, summary. Every field is required, including empty arrays. The shape is "
            '{"hypothesis":"UNKNOWN","confidence":"LOW","missing_information":[],"evidence_refs":[],"summary":"..."}. '
            "hypothesis must be one of TEMP_AVAILABILITY_CONFLICT, BUYER_UNREACHABLE, "
            "UNCLEAR_ADDRESS, SERVICE_DISRUPTION, UNSUPPORTED_REFUSAL, UNKNOWN. confidence must be LOW, MEDIUM, "
            "or HIGH. Use only supplied evidence IDs in evidence_refs. Preserve uncertainty and do not infer "
            "facts that are not supported. Use only these missing_information values: buyer_intent, "
            "address_landmark, refusal_evidence, failure_context. For RECIPIENT_UNAVAILABLE with unknown "
            "buyer intent, one unanswered call does not establish a persistently unreachable buyer: use "
            "TEMP_AVAILABILITY_CONFLICT at MEDIUM confidence and mark buyer_intent missing. Reserve "
            "BUYER_UNREACHABLE for repeated failed contact evidence or a confirmed invalid contact route. "
            "Do not propose an action, decide policy, or reveal chain-of-thought; "
            "summary must be a short evidence-grounded explanation."
        )
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


mock_reasoner: Reasoner = DeterministicMockReasoner()
