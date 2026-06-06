from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.campaign_signals import (
    CampaignSignalBridge,
    CampaignSignalCategory,
    CampaignSignalManager,
    CampaignSignalSeverity,
    ObservationWorkRefresher,
)
from telegram_app.work_items import WorkItemManager


def test_campaign_signal_manager_dedupes_same_unresolved_signal(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = CampaignSignalManager(campaigns_root)
    bridge = CampaignSignalBridge(manager)

    first = bridge.record(
        campaign_id="cmp-1",
        source_kind="live_execution",
        source_ref="action-1",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.MEDIUM,
        summary="A live action was blocked by policy.",
        account_id="reader-1",
        happened_at=datetime(2026, 5, 24, 8, 0, tzinfo=UTC),
        review_eligible=True,
    )
    second = bridge.record(
        campaign_id="cmp-1",
        source_kind="live_execution",
        source_ref="action-2",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.HIGH,
        summary="The same policy block happened again.",
        account_id="reader-1",
        context_refs=["attempt:2"],
        happened_at=datetime(2026, 5, 24, 8, 5, tzinfo=UTC),
        review_eligible=True,
    )

    signals = manager.list_for_campaign("cmp-1")

    assert first.signal_id == second.signal_id
    assert len(signals) == 1
    assert signals[0].occurrence_count == 2
    assert signals[0].severity is CampaignSignalSeverity.HIGH
    assert signals[0].summary == "The same policy block happened again."
    assert signals[0].context_refs == ["attempt:2"]
    assert signals[0].last_happened_at == datetime(2026, 5, 24, 8, 5, tzinfo=UTC)


def test_signal_bridge_creates_and_reuses_observation_work_when_review_pressure_exists(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    bridge = CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
    )

    bridge.record(
        campaign_id="cmp-1",
        source_kind="live_execution",
        source_ref="action-flagged",
        signal_type="account_flagged_or_banned",
        severity=CampaignSignalSeverity.CRITICAL,
        summary="Managed account `reader-1` was marked flagged.",
        account_id="reader-1",
        happened_at=datetime(2026, 5, 24, 9, 0, tzinfo=UTC),
        review_eligible=True,
    )
    bridge.record(
        campaign_id="cmp-1",
        source_kind="live_execution",
        source_ref="action-community",
        signal_type="community_paused_for_risk",
        severity=CampaignSignalSeverity.HIGH,
        summary="Community path `-100123` was risk-paused after repeated write friction.",
        account_id="reader-2",
        community_id="-100123",
        happened_at=datetime(2026, 5, 24, 9, 5, tzinfo=UTC),
        review_eligible=True,
    )

    observation_items = [
        item
        for item in work_item_manager.list_for_campaign("cmp-1")
        if item.work_type == "observation"
    ]

    assert len(observation_items) == 1
    assert observation_items[0].owner_role == "observation"
    assert observation_items[0].context_refs and len(observation_items[0].context_refs) == 2
    assert observation_items[0].refresh_reason == "Community path `-100123` was risk-paused after repeated write friction."


def test_signal_bridge_does_not_create_observation_work_for_non_review_signal(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    bridge = CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
    )

    bridge.record(
        campaign_id="cmp-1",
        source_kind="live_execution",
        source_ref="action-rate-limit",
        signal_type="account_rate_limited",
        severity=CampaignSignalSeverity.MEDIUM,
        summary="Managed account `reader-1` hit a rate limit.",
        account_id="reader-1",
        happened_at=datetime(2026, 5, 24, 9, 10, tzinfo=UTC),
        review_eligible=False,
    )

    assert signal_manager.list_for_campaign("cmp-1")
    assert work_item_manager.list_for_campaign("cmp-1") == []


def test_signal_bridge_infers_opportunity_and_yield_categories(tmp_path) -> None:
    manager = CampaignSignalManager(tmp_path / "campaigns")
    bridge = CampaignSignalBridge(manager)

    opportunity = bridge.record(
        campaign_id="cmp-1",
        source_kind="qualification",
        source_ref="conv-1",
        signal_type="pricing_interest",
        severity=CampaignSignalSeverity.MEDIUM,
        summary="Lead asked about pricing.",
        conversation_id="conv-1",
    )
    yield_signal = bridge.record(
        campaign_id="cmp-1",
        source_kind="qualification_handoff",
        source_ref="conv-1",
        signal_type="handoff_delivered",
        severity=CampaignSignalSeverity.HIGH,
        summary="Delivered the handoff successfully.",
        conversation_id="conv-1",
    )

    assert opportunity.category is CampaignSignalCategory.OPPORTUNITY
    assert yield_signal.category is CampaignSignalCategory.YIELD
