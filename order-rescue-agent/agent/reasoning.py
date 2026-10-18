from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pydantic import ValidationError

from .schemas import (
    AgentDecision,
    Assessment,
    BiCaseInput,
    BuyerIntent,
    CaseEvent,
    Confidence,
    DecisionRoute,
    DecisionStage,
    DeliveryContext,
    Evidence,
    EventType,
    Hypothesis,
)


class Reasoner(Protocol):
    """Replaceable interface for deterministic V0 or future structured model reasoning."""

    def assess(
        self,
        context: DeliveryContext,
        evidence: list[Evidence],
        *,
        case_input: BiCaseInput | None = None,
    ) -> Assessment: ...


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


class DeterministicMockReasoner:
    def assess(
        self,
        context: DeliveryContext,
        evidence: list[Evidence],
        *,
        case_input: BiCaseInput | None = None,
    ) -> Assessment:
        refs = [item.evidence_id for item in evidence]
        if case_input is not None:
            return self._assess_bi_case(case_input, context, evidence)
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

    def _assess_bi_case(
        self, case: BiCaseInput, context: DeliveryContext, evidence: list[Evidence]
    ) -> Assessment:
        evidence_refs = [item.evidence_id for item in evidence]
        status = (case.raw_status or "").upper()
        raw = " ".join((case.raw_reason or "", case.courier_note or "")).lower()
        extra = case.extra_context
        outcomes = {item.get("outcome") for item in case.contact_evidence}
        signal = case.disruption_signal
        new_events = [item for item in evidence if item.provenance in {"simulated_bi_event", "simulated_buyer_reply"}]
        event_text = " ".join((item.raw_text or item.value) for item in new_events).lower()
        event_kind = new_events[-1].kind.upper() if new_events else ""
        event = getattr(context, "buyer_intent", BuyerIntent.UNKNOWN)
        unknown_intent = event is BuyerIntent.UNKNOWN
        missing: list[str] = []

        if extra.get("duplicate_of") or extra.get("latest_status") in {"DELIVERED", "RETURNED"}:
            hypothesis, summary = Hypothesis.DATA_QUALITY_INVALID, "Duplicate/stale event is not a new delivery failure."
        elif extra.get("pii_detected"):
            hypothesis, summary = Hypothesis.DATA_QUALITY_INVALID, "PII marker requires dropping the input before assessment."
        elif extra.get("damage_flag") or "parcel_damaged" in outcomes:
            hypothesis, summary = Hypothesis.PARCEL_DAMAGE, "Courier evidence indicates parcel damage; Ops review is required."
        elif extra.get("hub_return_scan_found") is False and extra.get("hours_since_failed", 0) >= 72:
            hypothesis, summary = Hypothesis.OFF_SYSTEM_HOLD_SUSPECTED, "Missing hub return scan and stale status require Ops verification."
        elif case.return_state in {"started", "completed"} or self._deadline_expired(case) or "chuyển hoàn tại trạm" in raw or "đã hoàn về" in raw:
            hypothesis, summary = Hypothesis.LIFECYCLE_CLOSED, "Return lifecycle or decision deadline is closed."
        elif event_kind == "BUYER_REPLY" and any(term in event_text for term in ("không có cuộc gọi", "no call", "no calls")):
            hypothesis, summary = Hypothesis.RECORD_CONFLICT, "Buyer report conflicts with the courier contact record; human review is required."
        elif event_kind == "DISRUPTION_RESOLVED":
            hypothesis, summary = Hypothesis.TEMP_AVAILABILITY_CONFLICT, "The operational disruption is reported as cleared; buyer intent still needs confirmation."
        elif case.actor_role == "SELLER" and extra.get("pending_sender_confirmation"):
            hypothesis, summary = Hypothesis.TEMP_AVAILABILITY_CONFLICT, "This case is waiting for authorized seller confirmation."
        elif "RECIPIENT_UNAVAILABLE" == status and ("cổng đóng" in raw or "không được lên" in raw):
            hypothesis, summary = Hypothesis.ACCESS_RESTRICTION, "Access restrictions prevented the courier from reaching the recipient."
        elif status == "DELIVERY_FAILED_OTHER" and any(token in raw for token in ("không vào được", "không được lên", "bảo vệ chung cư")):
            hypothesis, summary = Hypothesis.ACCESS_RESTRICTION, "Building access rules prevented the courier from reaching the recipient."
        elif status == "ADDRESS_ISSUE" and ("đã chuyển đi" in raw or "dọn đi" in raw):
            hypothesis, summary = Hypothesis.ADDRESS_MISMATCH, "Available evidence indicates the registered address or map pin conflicts with the delivery location."
        elif status == "ADDRESS_ISSUE":
            if extra.get("legacy_admin_unit_flag"):
                hypothesis, summary = Hypothesis.LEGACY_ADMIN_ADDRESS, "The registered administrative-area name may be outdated."
            elif any(token in raw for token in ("không đúng", "chuyển đi", "đường khác", "mâu thuẫn")):
                hypothesis, summary = Hypothesis.ADDRESS_MISMATCH, "Delivery notes indicate the registered address conflicts with the actual location."
            else:
                hypothesis, summary = Hypothesis.ADDRESS_LANDMARK_UNCLEAR, "The address lacks a reliable landmark or delivery detail."
        elif status == "REFUSED":
            if "recipient_denies_order" in outcomes:
                hypothesis, summary = Hypothesis.BUYER_INTENT_UNCERTAIN, "The recipient does not recognize the order; sender intent and recipient awareness need review."
            elif "answered_negotiating" in outcomes:
                hypothesis, summary = Hypothesis.BUYER_INTENT_UNCERTAIN, "The recipient is negotiating rather than clearly accepting or refusing the order."
            elif outcomes.intersection({"direct_refusal", "confirmed_refusal"}):
                hypothesis, summary = Hypothesis.REFUSAL_CONFIRMED, "Direct evidence records a refusal; route to authorized review."
            else:
                hypothesis, summary = Hypothesis.REFUSAL_UNSUPPORTED, "A refusal label lacks sufficient supporting evidence."
        elif status == "CANCELLED_IN_TRANSIT":
            hypothesis, summary = Hypothesis.REFUSAL_CONFIRMED, "A platform cancellation event was recorded during delivery."
        elif status == "DELIVERY_FAILED_OTHER" and ("đổi cách thanh toán" in raw or "chuyển khoản" in raw):
            hypothesis, summary = Hypothesis.OUT_OF_SCOPE_REQUEST, "The request changes payment terms, which the agent cannot execute."
        elif status == "DELIVERY_FAILED_OTHER" and "kiện hàng hư hỏng" in raw:
            hypothesis, summary = Hypothesis.PARCEL_DAMAGE, "Courier evidence indicates parcel damage; Ops review is required."
        elif extra.get("orderer_differs_from_recipient"):
            hypothesis, summary = Hypothesis.BUYER_INTENT_UNCERTAIN, "The person at the address does not recognize the order; orderer intent needs confirmation."
        elif status == "DELIVERY_FAILED_OTHER" and ("cod" in raw or "thanh toán" in raw or "tiền" in raw):
            hypothesis, summary = Hypothesis.PAYMENT_OBSTACLE_COD, "The recorded failure is a temporary COD payment obstacle."
        elif signal.get("flag") and signal.get("verified"):
            route = extra.get("parcel_route")
            scope = signal.get("scope") or ""
            scope_match = not route or route in scope or scope.endswith("ALL")
            if not scope_match:
                hypothesis, summary = Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, "The disruption signal does not match this parcel route."
            elif signal.get("type") == "PEAK_CAPACITY":
                hypothesis, summary = Hypothesis.CAPACITY_PEAK, "A verified capacity signal is present; it is not evidence of buyer fault."
            else:
                hypothesis, summary = Hypothesis.SERVICE_DISRUPTION, "A verified, route-matched disruption signal explains the failed delivery."
        elif signal.get("flag"):
            if signal.get("type") == "PEAK_CAPACITY":
                hypothesis, summary = Hypothesis.CAPACITY_PEAK, "A capacity signal is present; it is not evidence of buyer fault."
            else:
                hypothesis, summary = Hypothesis.SERVICE_DISRUPTION, "A disruption signal may explain the failed delivery but is not verified."
        elif status == "DELIVERY_FAILED_OTHER" and any(token in raw for token in ("ngập", "mưa lớn", "đường vào")):
            hypothesis, summary = Hypothesis.SERVICE_DISRUPTION, "The courier reports adverse route conditions without a verified signal."
        elif "invalid_number" in outcomes:
            hypothesis, summary = Hypothesis.CONTACT_DATA_INVALID, "The contact log reports an invalid phone number."
        elif "answered_dispute" in outcomes:
            hypothesis, summary = Hypothesis.REFUSAL_UNSUPPORTED, "The buyer disputes the item; the delivery failure needs human review."
        elif "cannot_pay_now" in outcomes or status == "DELIVERY_FAILED_OTHER" and "chưa đủ tiền" in raw:
            hypothesis, summary = Hypothesis.PAYMENT_OBSTACLE_COD, "The buyer needs time to prepare COD payment."
        elif status == "CONTACT_FAILED" and (sum(int(item.get("n", 0) or 0) for item in case.contact_evidence) < 3):
            hypothesis, summary = Hypothesis.RECORD_CONFLICT, "Contact evidence is incomplete for the reported failure."
        elif status == "CONTACT_FAILED":
            hypothesis, summary = Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, "Repeated contact attempts failed; the cause remains unknown."
        elif status == "RESCHEDULED_BY_BUYER":
            hypothesis, summary = Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, "A reschedule was recorded but the buyer could not be reached at the agreed time."
        elif extra.get("service_condition_note") == "remote_route_infrequent":
            hypothesis, summary = Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, "The remote route follows an infrequent service schedule; next route timing is unknown."
        elif status == "RECIPIENT_UNAVAILABLE":
            hypothesis, summary = Hypothesis.TEMP_AVAILABILITY_CONFLICT, "The recipient was unavailable; current buyer intent is not yet confirmed."
        else:
            hypothesis, summary = Hypothesis.UNKNOWN, "Available BI input is insufficient to support a narrower cause."

        if context.buyer_intent is BuyerIntent.CONDITIONAL:
            hypothesis = Hypothesis.OUT_OF_SCOPE_REQUEST
            summary = "The reply contains a condition the agent cannot promise or execute."
        elif context.buyer_intent is BuyerIntent.DECLINES:
            hypothesis = Hypothesis.REFUSAL_CONFIRMED
            summary = "The buyer explicitly declines delivery; refund or return decisions remain with an authorized human."

        if hypothesis in {Hypothesis.TEMP_AVAILABILITY_CONFLICT, Hypothesis.BUYER_INTENT_UNCERTAIN,
                          Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, Hypothesis.ACCESS_RESTRICTION,
                          Hypothesis.ADDRESS_LANDMARK_UNCLEAR, Hypothesis.LEGACY_ADMIN_ADDRESS,
                          Hypothesis.PAYMENT_OBSTACLE_COD, Hypothesis.CAPACITY_PEAK} and unknown_intent:
            missing.append("buyer_intent")
        if hypothesis is Hypothesis.ADDRESS_LANDMARK_UNCLEAR:
            landmark_present = any(term in event_text for term in ("cạnh", "sau", "đầu hẻm", "mốc", "block", "căn", "số "))
            if not landmark_present:
                if extra.get("address_type") == "APARTMENT":
                    missing.append("block_floor_unit")
                elif "không số nhà" in raw:
                    missing.append("house_number_or_landmark")
                else:
                    missing.append("landmark")
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and event_kind == "DISRUPTION_RESOLVED" and unknown_intent:
            missing.append("buyer_intent")
        if hypothesis in {Hypothesis.TEMP_AVAILABILITY_CONFLICT, Hypothesis.ACCESS_RESTRICTION} and not event_text:
            if "buổi tối" in raw:
                missing.append("availability")
            if "đi công tác xa" in raw:
                missing.append("return_date")
            if "cổng đóng" in raw:
                missing.append("working_day_availability")
            if outcomes.intersection({"third_party_answered", "answered_by_neighbor"}) or "hàng xóm" in raw:
                missing.append("third_party_receipt_ok")
            if "bảo vệ" in raw or "chung cư" in raw or "sảnh" in raw:
                missing.append("pickup_point_at_gate")
        if hypothesis is Hypothesis.RECORD_CONFLICT:
            missing = ["call_log_completeness"] if not new_events else []
        if hypothesis is Hypothesis.ADDRESS_MISMATCH:
            missing = ["verified_address"]
        if hypothesis is Hypothesis.LEGACY_ADMIN_ADDRESS:
            missing = ["current_admin_unit_or_landmark"]
            if unknown_intent:
                missing.append("buyer_intent")
        if hypothesis is Hypothesis.PARCEL_DAMAGE:
            missing = ["damage_record"]
        if hypothesis is Hypothesis.PAYMENT_OBSTACLE_COD and "chưa đủ tiền" in raw:
            missing = ["buyer_intent", "ability_to_pay"]
        if hypothesis is Hypothesis.PAYMENT_OBSTACLE_COD:
            missing = ["buyer_intent", "ability_to_pay"]
        if hypothesis is Hypothesis.CONTACT_DATA_INVALID:
            missing = ["buyer_intent"] if event_kind == "SELLER_UPDATE" else ["valid_contact"]
        if hypothesis is Hypothesis.BUYER_INTENT_UNCERTAIN and extra.get("orderer_differs_from_recipient"):
            missing = ["orderer_intent", "recipient_awareness"]
        if hypothesis is Hypothesis.BUYER_INTENT_UNCERTAIN and context.buyer_intent is BuyerIntent.WANTS:
            missing = []
        if hypothesis is Hypothesis.BUYER_INTENT_UNCERTAIN and "answered_negotiating" in outcomes:
            missing = ["buyer_intent"]
        if hypothesis is Hypothesis.REFUSAL_UNSUPPORTED:
            if case.raw_status == "REFUSED" and not case.contact_evidence:
                missing = ["contact_log", "visit_evidence", "buyer_statement"]
            elif "answered_dispute" in outcomes:
                missing = ["listing_vs_parcel_evidence"]
            elif extra.get("inspection_service_enabled") == "UNKNOWN":
                missing = ["inspection_service_status", "seller_setting"]
        if hypothesis is Hypothesis.SERVICE_DISRUPTION:
            if not signal.get("verified") or not signal.get("source"):
                missing.append("disruption_source")
            if signal.get("flag") and (not signal.get("scope") or signal.get("scope") == "unknown"):
                missing.append("scope")
            if signal.get("verified"):
                missing = ["recovery_point"]
            elif case.raw_status == "DELIVERY_FAILED_OTHER" and "ngập" in raw:
                if context.buyer_intent is BuyerIntent.UNKNOWN:
                    missing.append("buyer_intent")
            elif context.buyer_intent is BuyerIntent.UNKNOWN and case.raw_status == "DELIVERY_FAILED_OTHER" and "ngập" in raw:
                missing.append("buyer_intent")
        if hypothesis is Hypothesis.OFF_SYSTEM_HOLD_SUSPECTED:
            missing = ["hub_scan", "return_state", "decision_deadline"]
        if hypothesis is Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE:
            if case.return_state in {"unknown", None}:
                missing = ["return_state", "decision_deadline"]
            elif not case.decision_deadline:
                missing.append("decision_deadline")
            if extra.get("service_condition_note") == "remote_route_infrequent":
                missing = ["buyer_intent", "next_route_date"]
            elif "thuê bao tắt máy" in raw:
                missing.append("alternate_contact_channel")
            elif "chuông đổ" in raw:
                missing.append("cause")
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and not case.decision_deadline:
            missing.append("decision_deadline")
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and "third_party_answered" in outcomes:
            missing = ["buyer_intent", "return_date"]
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and event_kind == "BUYER_REPLY" and "người nhà có thể nhận hộ" in event_text:
            missing = ["third_party_receipt_ok"]
        if hypothesis is Hypothesis.ADDRESS_MISMATCH and ("đã chuyển đi" in raw or "dọn đi" in raw):
            missing = ["buyer_intent", "new_address_authorized"]
        if hypothesis is Hypothesis.ADDRESS_LANDMARK_UNCLEAR and extra.get("map_pin_mismatch"):
            missing = ["landmark", "buyer_intent"]
        if hypothesis is Hypothesis.ADDRESS_LANDMARK_UNCLEAR and "không tìm thấy lối vào" in raw:
            missing = ["landmark"]
        if case.actor_role == "SELLER" and extra.get("pending_sender_confirmation") and event_kind != "SELLER_REPLY":
            missing = ["sender_decision", "buyer_intent"]
        if hypothesis is Hypothesis.REFUSAL_UNSUPPORTED and extra.get("inspection_service_enabled") == "UNKNOWN":
            missing = ["inspection_service_status", "seller_setting"]
        if event_kind in {"BUYER_REPLY", "BUYER_REPLY_LATE"} and context.buyer_intent is BuyerIntent.WANTS and case.raw_status in {"CONTACT_FAILED", "RESCHEDULED_BY_BUYER"} and case.attempts_remaining != 0 and hypothesis not in {Hypothesis.RECORD_CONFLICT, Hypothesis.CAPACITY_PEAK}:
            hypothesis = Hypothesis.TEMP_AVAILABILITY_CONFLICT
            summary = "The buyer explicitly confirms delivery intent after the contact issue."
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and context.buyer_intent is BuyerIntent.WANTS:
            missing = [item for item in missing if item != "buyer_intent"]
        if context.buyer_intent is BuyerIntent.WANTS and hypothesis is Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE:
            missing = [item for item in missing if item not in {"buyer_intent", "alternate_contact_channel", "cause"}]
        if hypothesis is Hypothesis.LEGACY_ADMIN_ADDRESS and context.buyer_intent is BuyerIntent.WANTS:
            missing = []
        if event_kind == "BUYER_REPLY" and context.buyer_intent is BuyerIntent.WANTS and "sóng lại" in event_text:
            missing = [item for item in missing if item != "alternate_contact_channel"]
        if event_kind == "BUYER_REPLY" and context.buyer_intent is BuyerIntent.WANTS and "người nhà có thể nhận hộ" in event_text:
            missing = [item for item in missing if item != "third_party_receipt_ok"]
        if event_kind == "BUYER_REPLY" and context.buyer_intent is BuyerIntent.WANTS and "chuẩn bị đủ tiền" in event_text:
            missing = [item for item in missing if item != "ability_to_pay"]
        if event_kind == "BUYER_REPLY" and context.buyer_intent is BuyerIntent.WANTS and extra.get("service_condition_note") == "remote_route_infrequent":
            hypothesis = Hypothesis.TEMP_AVAILABILITY_CONFLICT
            summary = "The buyer confirms delivery intent for the remote route."
            missing = []
        if hypothesis is Hypothesis.LEGACY_ADMIN_ADDRESS and context.buyer_intent is BuyerIntent.WANTS:
            missing = []
        if hypothesis in {Hypothesis.REFUSAL_CONFIRMED,
                          Hypothesis.SECURITY_INPUT_ANOMALY,
                          Hypothesis.DATA_QUALITY_INVALID, Hypothesis.LIFECYCLE_CLOSED}:
            missing = []

        if context.buyer_intent is BuyerIntent.WANTS:
            missing = [item for item in missing if item != "buyer_intent"]
            if hypothesis is Hypothesis.ADDRESS_LANDMARK_UNCLEAR and any(term in event_text for term in ("cạnh", "sau", "đầu hẻm", "mốc", "block", "căn", "số ")):
                missing = [item for item in missing if item != "landmark"]
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and context.buyer_intent is BuyerIntent.WANTS:
            summary = "The buyer confirmed they still want delivery; no delivery time has been promised."

        direct_reply = bool(new_events)
        confidence = Confidence.MEDIUM
        if context.buyer_intent is BuyerIntent.CONDITIONAL and direct_reply:
            confidence = Confidence.HIGH
        elif context.buyer_intent is BuyerIntent.WANTS:
            weak_reply = (
                hypothesis in {Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, Hypothesis.SERVICE_DISRUPTION,
                               Hypothesis.BUYER_INTENT_UNCERTAIN}
                or extra.get("service_condition_note") == "remote_route_infrequent"
                or case.actor_role == "SELLER"
                or any(item.get("outcome") in {"no_answer", "phone_off"} for item in case.contact_evidence)
            )
            confidence = Confidence.MEDIUM if weak_reply else Confidence.HIGH
        elif hypothesis in {Hypothesis.UNKNOWN, Hypothesis.RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE,
                            Hypothesis.REFUSAL_UNSUPPORTED, Hypothesis.OFF_SYSTEM_HOLD_SUSPECTED,
                            Hypothesis.BUYER_INTENT_UNCERTAIN, Hypothesis.RECORD_CONFLICT}:
            confidence = Confidence.LOW
        if hypothesis in {Hypothesis.LIFECYCLE_CLOSED, Hypothesis.PARCEL_DAMAGE,
                          Hypothesis.SECURITY_INPUT_ANOMALY, Hypothesis.DATA_QUALITY_INVALID,
                          Hypothesis.REFUSAL_CONFIRMED, Hypothesis.ADDRESS_LANDMARK_UNCLEAR,
                          Hypothesis.OUT_OF_SCOPE_REQUEST, Hypothesis.PAYMENT_OBSTACLE_COD,
                          Hypothesis.CONTACT_DATA_INVALID}:
            confidence = Confidence.HIGH
        if hypothesis is Hypothesis.ADDRESS_LANDMARK_UNCLEAR and extra.get("map_pin_mismatch"):
            confidence = Confidence.MEDIUM if context.buyer_intent is not BuyerIntent.WANTS else Confidence.HIGH
        if hypothesis is Hypothesis.ACCESS_RESTRICTION and "không được lên" in raw:
            confidence = Confidence.HIGH
        if hypothesis is Hypothesis.SERVICE_DISRUPTION:
            confidence = Confidence.HIGH if signal.get("verified") else Confidence.MEDIUM if case.raw_status == "DELIVERY_FAILED_OTHER" and "ngập" in raw else Confidence.LOW
        if hypothesis is Hypothesis.PARCEL_DAMAGE and missing:
            confidence = Confidence.HIGH
        if hypothesis is Hypothesis.TEMP_AVAILABILITY_CONFLICT and context.buyer_intent is BuyerIntent.UNKNOWN:
            if outcomes.intersection({"no_answer", "phone_off"}) or extra.get("pending_sender_confirmation"):
                confidence = Confidence.LOW
        if hypothesis is Hypothesis.BUYER_INTENT_UNCERTAIN and context.buyer_intent is BuyerIntent.UNKNOWN and not extra.get("orderer_differs_from_recipient"):
            confidence = Confidence.MEDIUM
        if hypothesis is Hypothesis.CONTACT_DATA_INVALID and event_kind == "SELLER_UPDATE":
            confidence = Confidence.MEDIUM
        if hypothesis is Hypothesis.ACCESS_RESTRICTION and context.buyer_intent is BuyerIntent.WANTS:
            confidence = Confidence.HIGH
        if hypothesis is Hypothesis.CAPACITY_PEAK and context.buyer_intent is BuyerIntent.WANTS:
            confidence = Confidence.HIGH
        if hypothesis is Hypothesis.RECORD_CONFLICT:
            confidence = Confidence.LOW
        if event_kind in {"NO_REPLY", "TIMEOUT"} and hypothesis in {Hypothesis.ADDRESS_LANDMARK_UNCLEAR, Hypothesis.TEMP_AVAILABILITY_CONFLICT}:
            confidence = Confidence.MEDIUM
        return Assessment(
            hypothesis=hypothesis,
            confidence=confidence,
            missing_information=list(dict.fromkeys(missing)),
            evidence_refs=evidence_refs,
            summary=summary,
        )

    @staticmethod
    def _deadline_expired(case: BiCaseInput) -> bool:
        if not case.assessed_at or not case.decision_deadline:
            return False
        try:
            from datetime import datetime
            assessed = datetime.fromisoformat(case.assessed_at.replace("Z", "+00:00"))
            deadline = datetime.fromisoformat(case.decision_deadline.replace("Z", "+00:00"))
        except ValueError:
            return False
        return deadline <= assessed


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

        common = (
            "Return exactly one AgentDecision JSON object. Required fields: stage, assessment, "
            "route. assessment requires hypothesis, confidence, missing_information, evidence_refs, "
            "summary. Use only supplied evidence IDs in assessment.evidence_refs and evidence_refs. "
            "Do not invent observations. Routes are ASK, WAIT_FOR_EVENT, PROPOSE_RECOVERY. "
            "Actions are CLARIFY, STANDARD_REATTEMPT, HOLD_DISRUPTION, ESCALATE_REVIEW, NO_ACTION. "
            "The action is only a candidate; do not evaluate policy, authorize execution, or supply "
            "a final recommendation."
        )
        if stage is DecisionStage.INITIAL:
            stage_prompt = (
                "For INITIAL, assess current evidence and select one route. ASK requires target "
                "(BUYER, SELLER, or OPS) and information_request with a question and purpose. "
                "WAIT_FOR_EVENT requires target. PROPOSE_RECOVERY requires proposed_action and rationale."
            )
        else:
            stage_prompt = (
                "For AFTER_EVENT, extract buyer_intent (UNKNOWN, WANTS, DECLINES, or CONDITIONAL) "
                "and parsed_facts from the raw event, update assessment, and set route to "
                "PROPOSE_RECOVERY with proposed_action and short rationale. Include at least one "
                "concrete event fact. Represent ambiguous intent or no reply as UNKNOWN; do not guess."
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": common + " " + stage_prompt},
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
                if decision.target is None or request is None or not request.question.strip() or not request.purpose.strip():
                    raise RuntimeError("DeepSeek ASK decision is missing a target or question.")
            elif decision.route is DecisionRoute.WAIT_FOR_EVENT:
                if decision.target is None:
                    raise RuntimeError("DeepSeek WAIT_FOR_EVENT decision is missing a target.")
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
            no_reply = case_event.event_type in {EventType.NO_REPLY, EventType.TIMEOUT} or case_event.reply_received is False
            if (no_reply or observed_intent is BuyerIntent.UNKNOWN) and decision.buyer_intent is not BuyerIntent.UNKNOWN:
                raise RuntimeError("DeepSeek decision inferred buyer intent without supporting event evidence.")
            if observed_intent not in (None, BuyerIntent.UNKNOWN) and decision.buyer_intent not in (observed_intent, BuyerIntent.UNKNOWN):
                raise RuntimeError("DeepSeek decision buyer intent conflicts with the case event.")
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
        system_prompt = (
            "Assess this synthetic failed-delivery case using only the observable delivery context and evidence. "
            "Return one JSON object with exactly these fields: hypothesis, confidence, missing_information, "
            "evidence_refs, summary. Every field is required, including empty arrays. The shape is "
            '{"hypothesis":"UNKNOWN","confidence":"LOW","missing_information":[],"evidence_refs":[],"summary":"..."}. '
            "hypothesis must match the BI vocabulary: TEMP_AVAILABILITY_CONFLICT, ACCESS_RESTRICTION, "
            "ADDRESS_LANDMARK_UNCLEAR, ADDRESS_MISMATCH, LEGACY_ADMIN_ADDRESS, CONTACT_DATA_INVALID, "
            "RECIPIENT_UNREACHABLE_UNKNOWN_CAUSE, REFUSAL_UNSUPPORTED, REFUSAL_CONFIRMED, "
            "BUYER_INTENT_UNCERTAIN, PAYMENT_OBSTACLE_COD, SERVICE_DISRUPTION, CAPACITY_PEAK, RECORD_CONFLICT, "
            "LIFECYCLE_CLOSED, PARCEL_DAMAGE, OUT_OF_SCOPE_REQUEST, OFF_SYSTEM_HOLD_SUSPECTED, "
            "SECURITY_INPUT_ANOMALY, DATA_QUALITY_INVALID, or UNKNOWN. confidence must be LOW, MEDIUM, "
            "or HIGH. Use only supplied evidence IDs in evidence_refs. Preserve uncertainty and do not infer "
            "facts that are not supported. missing_information contains missing BI fields or evidence needs, "
            "for example buyer_intent or decision_deadline. For RECIPIENT_UNAVAILABLE with unknown "
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
