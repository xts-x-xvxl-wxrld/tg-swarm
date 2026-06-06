"""Helpers for the durable campaign conversion-target contract."""

from __future__ import annotations

import re
from typing import Any

from telegram_app.models.conversion_target import (
    ConversionTargetFamily,
    ConversionTargetKind,
    ConversionTargetRecord,
)

RAW_VALUE_KEY = "raw_value"
NORMALIZED_VALUE_KEY = "normalized_value"
DESTINATION_KIND_KEY = "destination_kind"
DESTINATION_FAMILY_KEY = "destination_family"
DELIVERY_MODE_KEY = "delivery_mode"
PROOF_REQUIREMENT_KEY = "proof_requirement"
ALLOWED_ACTION_TYPES_KEY = "allowed_action_types"
NEEDS_CLARIFICATION_KEY = "needs_clarification"
SOURCE_MESSAGE_REFS_KEY = "source_message_refs"

CONVERSION_TARGET_SIGNAL_KEY = "conversion_target_signal"

_TME_LINK_PATTERN = re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_+/=-]+", re.IGNORECASE)
_HANDLE_PATTERN = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{2,}")
_URL_PATTERN = re.compile(r"https?://[^\s)\],;]+", re.IGNORECASE)

_KIND_LABELS = {
    ConversionTargetKind.UNKNOWN: "Unresolved target",
    ConversionTargetKind.TELEGRAM_DM: "Telegram DM",
    ConversionTargetKind.TELEGRAM_BOT: "Telegram bot",
    ConversionTargetKind.TELEGRAM_GROUP: "Telegram group",
    ConversionTargetKind.TELEGRAM_CHANNEL: "Telegram channel",
    ConversionTargetKind.EXTERNAL_WEBSITE: "External website",
}


def build_conversion_target_data(
    intent_data: dict[str, Any] | None,
    *,
    existing_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the durable conversion-target contract from campaign intent."""
    existing_record = ConversionTargetRecord.from_dict(existing_data)
    intent_payload = intent_data if isinstance(intent_data, dict) else {}
    signal_payload = intent_payload.get(CONVERSION_TARGET_SIGNAL_KEY, {})
    signal = signal_payload if isinstance(signal_payload, dict) else {}

    raw_value = _first_non_empty(signal.get(RAW_VALUE_KEY, ""), existing_record.raw_value)
    normalized_value = _first_non_empty(
        signal.get(NORMALIZED_VALUE_KEY, ""),
        normalize_destination_reference(raw_value),
        existing_record.normalized_value,
    )
    kind = _resolve_destination_kind(
        signal.get("kind_hint", ""),
        raw_value=raw_value,
        normalized_value=normalized_value,
        fallback=existing_record.destination_kind,
    )
    if not raw_value and not normalized_value and kind is ConversionTargetKind.UNKNOWN:
        return {}

    source_message_refs = _merge_unique_strings(
        existing_record.source_message_refs,
        intent_payload.get(SOURCE_MESSAGE_REFS_KEY, []),
    )
    needs_clarification = bool(signal.get(NEEDS_CLARIFICATION_KEY, False))
    if not normalized_value:
        needs_clarification = True
    if kind is ConversionTargetKind.UNKNOWN:
        needs_clarification = True

    delivery_mode, proof_requirement, allowed_action_types = _contract_for_kind(kind)
    record = ConversionTargetRecord(
        raw_value=raw_value,
        normalized_value=normalized_value,
        destination_kind=kind,
        destination_family=_family_for_kind(kind),
        delivery_mode=delivery_mode,
        proof_requirement=proof_requirement,
        allowed_action_types=allowed_action_types,
        needs_clarification=needs_clarification,
        source_message_refs=source_message_refs,
    )
    return record.to_dict()


def build_conversion_target_summary(payload: dict[str, Any] | None) -> str:
    """Return a compact operator-facing summary for one conversion target."""
    record = ConversionTargetRecord.from_dict(payload)
    display_value = record.raw_value or record.normalized_value
    if not display_value:
        return "Conversion target is not set."

    label = _KIND_LABELS[record.destination_kind]
    summary = f"{label}: {display_value}"
    if record.needs_clarification:
        return summary + " (needs clarification)."
    return summary + "."


def prompt_safe_conversion_target_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact prompt-safe view of the conversion-target contract."""
    return {
        key: value
        for key, value in normalize_conversion_target_data(payload).items()
        if value not in ("", [], {}, None)
    }


def normalize_conversion_target_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize persisted conversion-target data into the durable shape."""
    return ConversionTargetRecord.from_dict(payload).to_dict()


def infer_destination_kind(value: str) -> str:
    """Infer the best current destination kind label from freeform operator text."""
    return _resolve_destination_kind("", raw_value=value, normalized_value=normalize_destination_reference(value)).value


def normalize_destination_reference(value: str) -> str:
    """Extract one normalized destination reference from a freeform phrase."""
    normalized = _normalize_text(value).strip("`")
    if not normalized:
        return ""

    telegram_match = _TME_LINK_PATTERN.search(normalized)
    if telegram_match:
        return _normalize_telegram_reference(telegram_match.group(0))

    handle_match = _HANDLE_PATTERN.search(normalized)
    if handle_match:
        return handle_match.group(0).lower()

    url_match = _URL_PATTERN.search(normalized)
    if url_match:
        return _strip_trailing_punctuation(url_match.group(0))

    return ""


def _resolve_destination_kind(
    kind_hint: Any,
    *,
    raw_value: str,
    normalized_value: str,
    fallback: ConversionTargetKind = ConversionTargetKind.UNKNOWN,
) -> ConversionTargetKind:
    hinted_kind = ConversionTargetKind._value2member_map_.get(str(kind_hint or "").strip(), ConversionTargetKind.UNKNOWN)
    if hinted_kind is not ConversionTargetKind.UNKNOWN:
        return hinted_kind

    lowered = _normalize_text(raw_value or normalized_value).lower()
    if normalized_value.startswith("@"):
        if normalized_value.endswith("bot") or "telegram bot" in lowered or " bot" in lowered:
            return ConversionTargetKind.TELEGRAM_BOT
        return ConversionTargetKind.TELEGRAM_DM

    lowered_reference = normalized_value.lower()
    if "t.me/" in lowered_reference:
        path = lowered_reference.split("t.me/", 1)[1].strip("/")
        if path.startswith("+") or "joinchat" in path:
            return ConversionTargetKind.TELEGRAM_GROUP
        if path.endswith("bot") or "telegram bot" in lowered or " bot" in lowered:
            return ConversionTargetKind.TELEGRAM_BOT
        if "telegram channel" in lowered or " channel" in lowered:
            return ConversionTargetKind.TELEGRAM_CHANNEL
        if any(keyword in lowered for keyword in ("group", "community", "chat")):
            return ConversionTargetKind.TELEGRAM_GROUP
        return ConversionTargetKind.TELEGRAM_DM

    if lowered_reference.startswith(("http://", "https://")):
        return ConversionTargetKind.EXTERNAL_WEBSITE

    if any(keyword in lowered for keyword in ("landing page", "signup page", "website", "web page", "site", "form")):
        return ConversionTargetKind.EXTERNAL_WEBSITE
    if "telegram bot" in lowered or " bot" in lowered:
        return ConversionTargetKind.TELEGRAM_BOT
    if "telegram channel" in lowered or " channel" in lowered:
        return ConversionTargetKind.TELEGRAM_CHANNEL
    if any(keyword in lowered for keyword in ("group", "community", "chat")):
        return ConversionTargetKind.TELEGRAM_GROUP
    if any(keyword in lowered for keyword in ("dm", "direct message", "inbox", "user")):
        return ConversionTargetKind.TELEGRAM_DM
    return fallback


def _family_for_kind(kind: ConversionTargetKind) -> ConversionTargetFamily:
    if kind in {
        ConversionTargetKind.TELEGRAM_DM,
        ConversionTargetKind.TELEGRAM_BOT,
        ConversionTargetKind.TELEGRAM_GROUP,
        ConversionTargetKind.TELEGRAM_CHANNEL,
    }:
        return ConversionTargetFamily.TELEGRAM
    if kind is ConversionTargetKind.EXTERNAL_WEBSITE:
        return ConversionTargetFamily.EXTERNAL
    return ConversionTargetFamily.UNKNOWN


def _contract_for_kind(kind: ConversionTargetKind) -> tuple[str, str, list[str]]:
    if kind is ConversionTargetKind.TELEGRAM_DM:
        return ("direct_message", "confirmed_direct_message_route", ["send_dm"])
    if kind is ConversionTargetKind.TELEGRAM_BOT:
        return ("bot_handoff", "bot_handoff_initiated", ["share_bot_link"])
    if kind is ConversionTargetKind.TELEGRAM_GROUP:
        return ("group_join_or_invite", "group_destination_delivered", ["share_group_link", "invite_to_group"])
    if kind is ConversionTargetKind.TELEGRAM_CHANNEL:
        return ("channel_subscription", "channel_destination_delivered", ["share_channel_link"])
    if kind is ConversionTargetKind.EXTERNAL_WEBSITE:
        return ("external_visit", "external_link_or_submission_path_delivered", ["share_external_link"])
    return ("clarification_required", "operator_clarification_required", [])


def _normalize_telegram_reference(value: str) -> str:
    normalized = _strip_trailing_punctuation(_normalize_text(value).strip("`")).lower()
    if normalized.startswith(("http://", "https://")):
        return normalized.replace("http://", "https://", 1)
    return f"https://{normalized}"


def _strip_trailing_punctuation(value: str) -> str:
    return value.rstrip(").,;]")


def _merge_unique_strings(existing_values: Any, new_values: Any) -> list[str]:
    merged: list[str] = []
    for value in [*_normalize_string_list(existing_values), *_normalize_string_list(new_values)]:
        if value not in merged:
            merged.append(value)
    return merged


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_values: list[str] = []
    for item in value:
        normalized_item = _normalize_text(item)
        if normalized_item and normalized_item not in normalized_values:
            normalized_values.append(normalized_item)
    return normalized_values


def _first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
