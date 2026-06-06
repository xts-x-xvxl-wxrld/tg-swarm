"""Bounded read-side broker for agent runtime inspection."""

from __future__ import annotations

from collections import Counter
from typing import Any

from telegram_app.campaign_setup import get_campaign_setup_state, setup_is_confirmed
from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
    StubAccountCapability,
    StubCommunityCapability,
    StubMembershipCapability,
    StubMessagingCapability,
)
from telegram_app.compiled_intents import CompiledIntentStore
from telegram_app.continuous_ops.storage import load_continuous_ops_state_for_workspace
from telegram_app.models import ScheduleRecord, ScheduleStatus, SessionRecord, WorkItemRecord
from telegram_app.scheduling import ScheduleManager
from telegram_app.work_items import WorkItemManager

_PROMPT_SAFE_ACCOUNT_KEYS = (
    "account_id",
    "tier",
    "health",
    "language",
    "geography",
    "warmup_day",
    "warmup_stage",
    "warmup_active",
    "join_count_24h",
    "rate_limit_until",
    "last_active",
)
_PROMPT_SAFE_PROFILE_KEYS = (
    "community_id",
    "name",
    "username",
    "type",
    "member_count",
    "verified",
    "restricted",
    "scam",
    "description",
    "linked_chat_id",
    "slowmode_seconds",
)


class AgentRuntimeBroker:
    """Aggregate runtime managers and bounded capability reads for reasoning surfaces."""

    def __init__(
        self,
        *,
        work_item_manager: WorkItemManager | None = None,
        schedule_manager: ScheduleManager | None = None,
        compiled_intent_store: CompiledIntentStore | None = None,
        account_capability: AccountCapability | None = None,
        community_capability: CommunityCapability | None = None,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
    ) -> None:
        self._work_item_manager = work_item_manager
        self._schedule_manager = schedule_manager
        self._compiled_intent_store = compiled_intent_store
        self._account_capability = account_capability
        self._community_capability = community_capability
        self._membership_capability = membership_capability
        self._messaging_capability = messaging_capability

    def list_active_work_items(self, session: SessionRecord) -> list[WorkItemRecord]:
        """Return the current open work items for the attached campaign."""
        if self._work_item_manager is None or not session.campaign_id:
            return []
        return self._work_item_manager.list_open_for_campaign(session.campaign_id)

    def list_active_schedules(self, session: SessionRecord) -> list[ScheduleRecord]:
        """Return the current active schedules for the attached campaign."""
        if self._schedule_manager is None or not session.campaign_id:
            return []
        return [
            schedule
            for schedule in self._schedule_manager.list_for_campaign(session.campaign_id)
            if schedule.status is ScheduleStatus.ACTIVE
        ]

    def build_prompt_context(
        self,
        session: SessionRecord,
        *,
        work_type: str | None = None,
        conversation_id: str | None = None,
        proposal_limit: int = 6,
    ) -> dict[str, Any]:
        """Return compact prompt-safe runtime summaries for one reasoning surface."""
        return {
            "campaign_readiness_summary": self.build_campaign_readiness_summary(session),
            "runtime_pressure_summary": self.build_runtime_pressure_summary(session),
            "traction_summary": self.build_traction_summary(session),
            "worker_health_summary": self.build_worker_health_summary(),
            "telegram_capability_summary": self.build_telegram_capability_summary(),
            "recent_proposal_outcomes": self.build_recent_proposal_summary(
                session,
                work_type=work_type,
                conversation_id=conversation_id,
                limit=proposal_limit,
            ),
        }

    def build_campaign_readiness_summary(self, session: SessionRecord) -> dict[str, Any]:
        """Return compact setup and campaign-readiness facts."""
        setup_state = get_campaign_setup_state(session)
        continuous_ops_state = self._load_continuous_ops_state(session)
        active_work_items = self.list_active_work_items(session)
        active_schedules = self.list_active_schedules(session)
        readiness_status = str(setup_state.get("readiness_status", "")).strip()
        missing_fields = setup_state.get("missing_fields", [])
        return _compact_dict(
            {
                "campaign_attached": bool(session.campaign_id and session.campaign_workspace_path),
                "setup_readiness_status": readiness_status,
                "setup_confirmed": setup_is_confirmed(setup_state),
                "missing_fields": missing_fields[:3] if isinstance(missing_fields, list) else [],
                "active_work_item_count": len(active_work_items),
                "active_schedule_count": len(active_schedules),
                "loop_status": continuous_ops_state.loop_status.value if continuous_ops_state is not None else "",
                "operator_attention_required": (
                    continuous_ops_state.operator_attention_required
                    if continuous_ops_state is not None
                    else False
                ),
            }
        )

    def build_runtime_pressure_summary(self, session: SessionRecord) -> dict[str, Any]:
        """Return compact loop-pressure facts for prompt context."""
        continuous_ops_state = self._load_continuous_ops_state(session)
        if continuous_ops_state is None:
            return {}
        return _compact_dict(
            {
                "loop_status": continuous_ops_state.loop_status.value,
                "status_summary": continuous_ops_state.status_summary,
                "blocked_reasons": continuous_ops_state.blocked_reasons[:3],
                "review_pending_work_types": continuous_ops_state.review_pending_work_types[:3],
                "reviewable_signal_count": continuous_ops_state.reviewable_signal_count,
                "unresolved_signal_count": continuous_ops_state.unresolved_signal_count,
                "highest_signal_severity": continuous_ops_state.highest_signal_severity,
                "latest_observation_attention": continuous_ops_state.latest_observation_attention,
                "latest_observation_next_step": continuous_ops_state.latest_observation_next_step,
            }
        )

    def build_traction_summary(self, session: SessionRecord) -> dict[str, Any]:
        """Return compact live-traction facts for prompt context."""
        continuous_ops_state = self._load_continuous_ops_state(session)
        if continuous_ops_state is None:
            return {}
        return _compact_dict(
            {
                "summary": continuous_ops_state.commercial_summary,
                "promising_active_thread_count": continuous_ops_state.promising_active_thread_count,
                "objection_heavy_thread_count": continuous_ops_state.objection_heavy_thread_count,
                "conversion_ready_thread_count": continuous_ops_state.conversion_ready_thread_count,
                "unresolved_high_opportunity_thread_count": (
                    continuous_ops_state.unresolved_high_opportunity_thread_count
                ),
                "stale_promising_thread_count": continuous_ops_state.stale_promising_thread_count,
                "high_yield_account_labels": continuous_ops_state.high_yield_account_labels[:3],
                "high_yield_community_labels": continuous_ops_state.high_yield_community_labels[:3],
            }
        )

    def build_worker_health_summary(self) -> dict[str, Any]:
        """Return compact backend and managed-account availability facts."""
        summary = {
            "compiled_intent_boundary": "enabled" if self._compiled_intent_store is not None else "unavailable",
            "capabilities": {
                "account_reads": self._availability_label(self._account_capability),
                "community_reads": self._availability_label(self._community_capability),
                "membership_reads": self._availability_label(self._membership_capability),
                "messaging_reads": self._availability_label(self._messaging_capability),
            },
        }
        roster_summary = self.build_account_roster_summary()
        if roster_summary:
            summary["account_roster"] = roster_summary
        capability_summary = self.build_telegram_capability_summary()
        if capability_summary:
            summary["telegram_capability_summary"] = capability_summary
        return _compact_dict(summary)

    def build_telegram_capability_summary(self) -> dict[str, Any]:
        """Return operator-relevant readiness for live Telegram reads."""
        if self._is_stub_runtime():
            return {
                "backend": "stub",
                "live_readiness": "stubbed",
                "operator_action_required": True,
                "summary": "Live Telegram capabilities are still running in stub mode.",
                "next_step": "Set TELEGRAM_CAPABILITY_BACKEND=telethon and run /addaccount to onboard a real Telegram account.",
            }

        roster_summary = self.build_account_roster_summary()
        if not roster_summary:
            return {
                "backend": "unavailable",
                "live_readiness": "unavailable",
                "operator_action_required": True,
                "summary": "Telegram capability wiring is unavailable in this runtime.",
            }

        if not roster_summary.get("live_ready"):
            account_count = int(roster_summary.get("account_count", 0) or 0)
            if account_count < 1:
                return {
                    "backend": str(roster_summary.get("source", "mtproto") or "mtproto"),
                    "live_readiness": "no_accounts",
                    "operator_action_required": True,
                    "summary": "The live Telegram backend is enabled, but no managed Telegram accounts are onboarded yet.",
                    "next_step": "Run /addaccount to onboard a Telegram account for live reads and execution.",
                    "account_count": account_count,
                }
            return {
                "backend": str(roster_summary.get("source", "mtproto") or "mtproto"),
                "live_readiness": "blocked",
                "operator_action_required": True,
                "summary": str(roster_summary.get("summary", "")).strip() or "Live Telegram capability is present but not ready yet.",
                "account_count": account_count,
            }

        return {
            "backend": str(roster_summary.get("source", "mtproto") or "mtproto"),
            "live_readiness": "live_ready",
            "operator_action_required": False,
            "summary": "Live Telegram read capabilities are ready.",
            "account_count": int(roster_summary.get("account_count", 0) or 0),
        }

    def build_recent_proposal_summary(
        self,
        session: SessionRecord,
        *,
        work_type: str | None = None,
        conversation_id: str | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Return compact recent proposal outcomes for future reasoning."""
        if self._compiled_intent_store is None or not session.campaign_id:
            return {}
        return self._compiled_intent_store.summarize_recent_outcomes(
            session.campaign_id,
            limit=limit,
            work_type=work_type,
            conversation_id=conversation_id,
        )

    def build_account_roster_summary(self) -> dict[str, Any]:
        """Return a prompt-safe account roster summary."""
        if self._account_capability is None:
            return {}
        result = self._account_capability.list_accounts()
        if not result.success:
            return {
                "available": False,
                "live_ready": False,
                "source": self._account_source_label(),
                "error": result.error,
            }
        accounts = result.data.get("accounts", [])
        if not isinstance(accounts, list):
            return {
                "available": False,
                "live_ready": False,
                "source": self._account_source_label(),
            }
        health_counts = Counter(
            str(account.get("health", "unknown")).strip() or "unknown"
            for account in accounts
            if isinstance(account, dict)
        )
        prompt_safe_accounts = [
            {
                key: account.get(key)
                for key in _PROMPT_SAFE_ACCOUNT_KEYS
                if account.get(key) not in ("", [], {}, None)
            }
            for account in accounts
            if isinstance(account, dict)
        ]
        source = self._account_source_label()
        live_ready = source != "stub" and bool(prompt_safe_accounts)
        return _compact_dict(
            {
                "available": live_ready,
                "live_ready": live_ready,
                "source": source,
                "account_count": len(prompt_safe_accounts),
                "health_counts": dict(sorted(health_counts.items())),
                "accounts": prompt_safe_accounts[:6],
                "summary": (
                    "Stub roster only. Enable the Telethon backend and onboard an account with /addaccount."
                    if source == "stub"
                    else (
                        "No managed Telegram accounts are onboarded yet."
                        if not prompt_safe_accounts
                        else "Managed Telegram accounts are available."
                    )
                ),
            }
        )

    def get_community_profile_snapshot(self, community_id: str) -> dict[str, Any] | None:
        """Return one prompt-safe live community profile snapshot."""
        if self._community_capability is None or not community_id.strip():
            return None
        result = self._community_capability.get_profile(community_id)
        if not result.success:
            return None
        community = result.data.get("community", {})
        if not isinstance(community, dict):
            return None
        snapshot = {
            key: community.get(key)
            for key in _PROMPT_SAFE_PROFILE_KEYS
            if community.get(key) not in ("", [], {}, None)
        }
        if not snapshot:
            return None
        return snapshot

    def _availability_label(self, dependency: object | None) -> str:
        if dependency is None:
            return "unavailable"
        if isinstance(
            dependency,
            (StubAccountCapability, StubCommunityCapability, StubMembershipCapability, StubMessagingCapability),
        ):
            return "stubbed"
        return "available"

    def _account_source_label(self) -> str:
        if isinstance(self._account_capability, StubAccountCapability):
            return "stub"
        return "mtproto"

    def _is_stub_runtime(self) -> bool:
        return any(
            isinstance(
                dependency,
                (StubAccountCapability, StubCommunityCapability, StubMembershipCapability, StubMessagingCapability),
            )
            for dependency in (
                self._account_capability,
                self._community_capability,
                self._membership_capability,
                self._messaging_capability,
            )
            if dependency is not None
        )

    def _load_continuous_ops_state(self, session: SessionRecord):
        if not session.campaign_workspace_path:
            return None
        return load_continuous_ops_state_for_workspace(session.campaign_workspace_path)


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", [], {}, None)
    }
