"""Telegram-friendly formatting helpers for live-ops responses."""

from __future__ import annotations

from telegram_app.live_ops.models import CampaignLiveOpsSnapshot, ControlAreaState


def format_snapshot(
    snapshot: CampaignLiveOpsSnapshot,
    *,
    headline: str,
    include_attention: bool = True,
    include_control_gaps: bool = True,
) -> str:
    """Render one compact live-ops snapshot for Telegram chat."""
    lines = [
        headline,
        (
            "Queue: "
            f"{snapshot.queued_count} queued, "
            f"{snapshot.retry_wait_count} retry-wait, "
            f"{snapshot.running_count} running, "
            f"{snapshot.blocked_count} blocked, "
            f"{snapshot.recent_success_count} recent success."
        ),
        (
            "Conversations: "
            f"{snapshot.review_inbound_count} inbound review, "
            f"{snapshot.pending_autonomous_review_count} autonomous review, "
            f"{snapshot.paused_conversation_count} paused, "
            f"{snapshot.escalated_conversation_count} escalated, "
            f"{snapshot.follow_up_due_count} follow-up due."
        ),
        (
            "Traction: "
            f"{snapshot.promising_active_thread_count} promising active, "
            f"{snapshot.objection_heavy_thread_count} objection-heavy, "
            f"{snapshot.conversion_ready_thread_count} conversion-ready, "
            f"{snapshot.unresolved_high_opportunity_thread_count} unresolved high-opportunity, "
            f"{snapshot.stale_promising_thread_count} stale promising."
        ),
        (
            "Autonomous replies: "
            f"group `{snapshot.group_reply_mode or 'unknown'}`, "
            f"dm `{snapshot.dm_reply_mode or 'unknown'}`."
        ),
    ]
    if snapshot.activation_status:
        activation_line = f"Activation: {snapshot.activation_status}"
        if snapshot.latest_batch_id:
            activation_line += f" (`{snapshot.latest_batch_id}`)"
        lines.append(activation_line)
    if snapshot.primary_goal:
        lines.append(f"Goal: {snapshot.primary_goal}")
    if snapshot.high_yield_account_labels or snapshot.high_yield_community_labels:
        hotspot_parts: list[str] = []
        if snapshot.high_yield_account_labels:
            hotspot_parts.append("accounts " + ", ".join(snapshot.high_yield_account_labels[:3]))
        if snapshot.high_yield_community_labels:
            hotspot_parts.append("communities " + ", ".join(snapshot.high_yield_community_labels[:3]))
        lines.append("Momentum hotspots: " + "; ".join(hotspot_parts) + ".")
    elif snapshot.commercial_summary:
        lines.append(f"Commercial summary: {snapshot.commercial_summary}")
    if include_attention:
        if snapshot.attention_items:
            lines.append("Needs attention:")
            lines.extend(
                f"- `{item.item_id}`: {item.summary} Say `{item.recommended_action}`."
                for item in snapshot.attention_items[:5]
            )
        else:
            lines.append("Needs attention: nothing urgent right now.")
    if include_control_gaps:
        control_lines = _format_control_gaps(snapshot.control_areas)
        lines.extend(control_lines)
    if snapshot.recommended_next_action:
        lines.append(f"Next step: {snapshot.recommended_next_action}")
    return "\n".join(lines).strip()


def format_review_list(review_lines: list[str], *, heading: str) -> str:
    """Render one compact pending-review list."""
    if not review_lines:
        return f"{heading}\nNo pending autonomous reviews right now."
    return "\n".join([heading, *review_lines]).strip()


def format_block_reason(headline: str, details: str, *, next_step: str = "") -> str:
    """Render one compact blocked-reason explanation."""
    lines = [headline, details]
    if next_step.strip():
        lines.append(f"Next step: {next_step.strip()}")
    return "\n".join(line for line in lines if line.strip()).strip()


def _format_control_gaps(control_areas: list[ControlAreaState]) -> list[str]:
    if not control_areas:
        return []
    confirmed = sum(1 for area in control_areas if area.status.value == "confirmed")
    default = sum(1 for area in control_areas if area.status.value == "default")
    gaps = [
        area
        for area in control_areas
        if area.status.value in {"unset", "default", "partial", "ambiguous"}
    ]
    if not gaps:
        return [f"Control readiness: {confirmed} confirmed. Nothing obvious is missing right now."]

    lines = [
        f"Control readiness: {confirmed} confirmed, {default} still on defaults, {len(gaps)} worth tightening.",
    ]
    for area in sorted(gaps, key=_control_gap_sort_key)[:5]:
        suffix = " Default is acceptable for now." if area.default_is_acceptable else ""
        lines.append(f"- {area.label}: {area.summary}{suffix}")
    return lines


def _control_gap_sort_key(area: ControlAreaState) -> tuple[int, str]:
    order = {
        "unset": 1,
        "ambiguous": 2,
        "partial": 3,
        "default": 4,
    }
    area_order = {
        "voice_profile": 1,
        "approved_claims": 2,
        "forbidden_claims": 3,
        "dm_reply_posture": 4,
        "group_reply_posture": 5,
        "community_tone_guidance": 6,
        "escalation_rules": 7,
    }
    return order.get(area.status.value, 99), area_order.get(area.area_key, 99), area.label
