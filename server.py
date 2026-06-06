# FastAPI entry point for the Telegram-native runtime and legacy agency API.

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
import uvicorn

from telegram_app import TelegramAppService, run_telegram_polling
from telegram_app.autonomous_send import AutonomousSendManager, AutonomousSendService
from telegram_app.campaign_assets import BotApiAttachmentDownloader, CampaignAssetIntakeCoordinator
from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalManager, ObservationWorkRefresher
from telegram_app.compiled_intents import CompiledIntentApplicator, CompiledIntentStore
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.engagement import ManagedAccountEngagementStore, ManagedAccountEventListener
from telegram_app.engagement_policy import CampaignEngagementPolicyManager, CampaignEngagementPolicyService
from telegram_app.engagement_brain import (
    AnthropicDraftTextGenerator,
    ConversationReviewDispatcher,
    ConversationReviewRunner,
    EngagementBrainContextBuilder,
    EngagementBrainCoordinator,
    EngagementBrainService,
)
from telegram_app.engagement_triage import CheapInboundTriageService
from telegram_app.external_conversations import (
    ExternalConversationManager,
    ExternalConversationProjector,
    ExternalConversationTimingService,
)
from telegram_app.live_execution import (
    LiveExecutionManager,
    LiveExecutionPolicyStateManager,
    LiveExecutionRunner,
    LiveExecutionService,
)
from telegram_app.live_ops import LiveOpsControlManager, LiveOpsService
from telegram_app.monitoring import (
    FanoutRuntimeEventLogger,
    JsonlRuntimeEventLogger,
    NullRuntimeEventLogger,
    RuntimeMonitoringThresholds,
    RuntimeEventLogger,
    RuntimeTraceContext,
    SqliteRuntimeMonitoringStore,
)
from telegram_app.prepared_execution import PreparedExecutionManager, PreparedExecutionService
from telegram_app.auth import AuthManager, JsonAuthStateStore
from telegram_app.campaigns import CampaignManager
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
from telegram_app.capabilities.mtproto import (
    AccountCapabilityImpl,
    AccountRegistry,
    CommunityCapabilityImpl,
    JsonlAuditLogger,
    MembershipCapabilityImpl,
    MessagingCapabilityImpl,
    TelethonAuthGateway,
    TelethonClientWrapper,
    TelethonSessionManager,
)
from telegram_app.operator_notifications import OperatorInterventionManager
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.qualification import QualificationManager, QualificationService
from telegram_app.scheduling import (
    ScheduleManager,
    ScheduledWorkDispatcher,
    ScheduledWorkRunner,
    SchedulerLeaseManager,
)
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramBotApiClient, TelegramResponse, TelegramUpdate
from telegram_app.work_items import WorkItemManager
from telegram_app.polling_runner import JsonTelegramPollingCursorStore


def _normalize_windows_path_env() -> None:
    """Keep Windows PATH aliases available for libraries that expect exact casing."""
    if os.name != "nt":
        return
    path_value = os.environ.get("Path", "").strip()
    upper_path_value = os.environ.get("PATH", "").strip()
    if upper_path_value and not path_value:
        os.environ["Path"] = upper_path_value
    elif path_value and not upper_path_value:
        os.environ["PATH"] = path_value


load_dotenv()
_normalize_windows_path_env()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_STATE_DIR = Path("activity-logs") / "telegram-runtime"
DEFAULT_TELEGRAM_DATA_DIR = Path("data")
DEFAULT_CAPABILITY_BACKEND = "stub"
DEFAULT_SCHEDULER_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_SCHEDULER_LEASE_TTL_SECONDS = 30
DEFAULT_LIVE_EXECUTION_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_LIVE_EXECUTION_CLAIM_TTL_SECONDS = 300
DEFAULT_CONVERSATION_REVIEW_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CONVERSATION_REVIEW_CLAIM_TTL_SECONDS = 300
DEFAULT_MONITORING_SUMMARY_HOURS = 24


@dataclass(slots=True)
class RuntimeDependencyBundle:
    """Compose startup-time runtime dependencies."""

    auth_manager: AuthManager | None = None
    account_registry: AccountRegistry | None = None
    account_capability: AccountCapability | None = None
    client_wrapper: TelethonClientWrapper | None = None
    community_capability: CommunityCapability | None = None
    engagement_store: ManagedAccountEngagementStore | None = None
    membership_capability: MembershipCapability | None = None
    messaging_capability: MessagingCapability | None = None


@dataclass(slots=True)
class TelegramRuntimeComponents:
    """Shared runtime objects reused by interactive and scheduler entrypoints."""

    campaign_manager: CampaignManager
    work_item_manager: WorkItemManager
    schedule_manager: ScheduleManager
    intervention_manager: OperatorInterventionManager
    continuous_ops_manager: ContinuousOpsManager
    session_manager: SessionManager
    approval_manager: ApprovalManager
    orchestrator: PurposeBuiltOrchestrator
    compiled_intent_store: CompiledIntentStore
    compiled_intent_applicator: CompiledIntentApplicator
    monitor: RuntimeEventLogger
    monitoring_store: SqliteRuntimeMonitoringStore
    monitoring_jsonl_path: Path
    dependency_bundle: RuntimeDependencyBundle


class WebhookRequest(BaseModel):
    webhook_url: str = Field(..., description="Public HTTPS webhook URL for Telegram callbacks.")


def create_telegram_app_service(state_dir: str | Path | None = None) -> TelegramAppService:
    """Build the thin Telegram runtime service with persistent local state."""
    components = build_runtime_components(state_dir)
    return _create_telegram_app_service_from_components(components)


def _create_telegram_app_service_from_components(components: TelegramRuntimeComponents) -> TelegramAppService:
    """Build the app-service facade from already-composed runtime components."""
    intake_coordinator = StructuredIntakeCoordinator(components.session_manager)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    asset_intake_coordinator = CampaignAssetIntakeCoordinator(
        components.session_manager,
        downloader=BotApiAttachmentDownloader(bot_token) if bot_token else None,
    )
    return TelegramAppService(
        session_manager=components.session_manager,
        approval_manager=components.approval_manager,
        orchestrator=components.orchestrator,
        intake_coordinator=intake_coordinator,
        asset_intake_coordinator=asset_intake_coordinator,
        auth_manager=components.dependency_bundle.auth_manager,
        account_capability=components.dependency_bundle.account_capability,
        campaign_manager=components.campaign_manager,
        intervention_manager=components.intervention_manager,
        continuous_ops_manager=components.continuous_ops_manager,
        monitor=components.monitor,
    )


def build_runtime_components(state_dir: str | Path | None = None) -> TelegramRuntimeComponents:
    """Compose the reusable runtime objects behind both app and scheduler entrypoints."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    monitor, monitoring_store, monitoring_jsonl_path = _build_runtime_monitor(runtime_state_dir)
    campaigns_root = _resolve_telegram_data_dir() / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    conversation_manager = ExternalConversationManager(campaigns_root)
    engagement_policy_service = CampaignEngagementPolicyService(CampaignEngagementPolicyManager(campaigns_root))
    intervention_manager = OperatorInterventionManager(
        campaign_manager,
        schedule_manager,
        signal_manager,
    )
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
        conversation_manager=conversation_manager,
        intervention_manager=intervention_manager,
    )
    live_execution_manager = LiveExecutionManager(campaigns_root)
    prepared_execution_manager = PreparedExecutionManager(campaigns_root)
    autonomous_send_manager = AutonomousSendManager(campaigns_root)
    control_manager = LiveOpsControlManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    session_manager = SessionManager(JsonSessionStore(runtime_state_dir / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(runtime_state_dir / "approvals.json"))
    dependency_bundle = _build_runtime_dependency_bundle(runtime_state_dir)
    policy_state_manager = LiveExecutionPolicyStateManager(_resolve_telegram_data_dir())
    prepared_execution_service = PreparedExecutionService(
        prepared_execution_manager,
        live_execution_manager,
        session_manager=session_manager,
        work_item_manager=work_item_manager,
    )
    live_execution_service = LiveExecutionService(
        live_execution_manager,
        conversation_manager=conversation_manager,
        campaign_manager=campaign_manager,
        account_registry=dependency_bundle.account_registry,
        policy_state_manager=policy_state_manager,
        engagement_policy_service=engagement_policy_service,
    )
    autonomous_send_service = AutonomousSendService(
        autonomous_send_manager,
        conversation_manager=conversation_manager,
        live_execution_service=live_execution_service,
    )
    live_ops_service = LiveOpsService(
        campaign_manager=campaign_manager,
        continuous_ops_manager=continuous_ops_manager,
        control_manager=control_manager,
        autonomous_send_manager=autonomous_send_manager,
        autonomous_send_service=autonomous_send_service,
        conversation_manager=conversation_manager,
        live_execution_service=live_execution_service,
        live_execution_policy_state_manager=policy_state_manager,
        prepared_execution_manager=prepared_execution_manager,
    )
    compiled_intent_applicator = CompiledIntentApplicator(
        schedule_manager=schedule_manager,
        work_item_manager=work_item_manager,
        campaign_manager=campaign_manager,
        conversation_manager=conversation_manager,
        live_ops_service=live_ops_service,
        live_execution_service=live_execution_service,
        prepared_execution_service=prepared_execution_service,
    )
    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        approval_manager=approval_manager,
        community_capability=dependency_bundle.community_capability,
        account_capability=dependency_bundle.account_capability,
        membership_capability=dependency_bundle.membership_capability,
        messaging_capability=dependency_bundle.messaging_capability,
        work_item_manager=work_item_manager,
        schedule_manager=schedule_manager,
        campaign_manager=campaign_manager,
        signal_manager=signal_manager,
        continuous_ops_manager=continuous_ops_manager,
        prepared_execution_service=prepared_execution_service,
        live_ops_service=live_ops_service,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
        monitor=monitor,
    )
    return TelegramRuntimeComponents(
        campaign_manager=campaign_manager,
        work_item_manager=work_item_manager,
        schedule_manager=schedule_manager,
        intervention_manager=intervention_manager,
        continuous_ops_manager=continuous_ops_manager,
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
        monitor=monitor,
        monitoring_store=monitoring_store,
        monitoring_jsonl_path=monitoring_jsonl_path,
        dependency_bundle=dependency_bundle,
    )


def create_scheduled_work_runner(state_dir: str | Path | None = None) -> ScheduledWorkRunner:
    """Build the dedicated recurring-work runner used by scheduler-only processes."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    components = build_runtime_components(runtime_state_dir)
    dispatcher = ScheduledWorkDispatcher(components.schedule_manager, components.orchestrator)
    lease_manager = SchedulerLeaseManager(
        runtime_state_dir,
        lease_ttl_seconds=int(
            os.getenv("TELEGRAM_SCHEDULER_LEASE_TTL_SECONDS", str(DEFAULT_SCHEDULER_LEASE_TTL_SECONDS))
        ),
    )
    return ScheduledWorkRunner(
        dispatcher,
        lease_manager,
        poll_interval_seconds=float(
            os.getenv("TELEGRAM_SCHEDULER_POLL_INTERVAL_SECONDS", str(DEFAULT_SCHEDULER_POLL_INTERVAL_SECONDS))
        ),
    )


def create_managed_account_event_listener(state_dir: str | Path | None = None) -> ManagedAccountEventListener:
    """Build the dedicated managed-account inbound listener worker."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    dependency_bundle = _build_runtime_dependency_bundle(runtime_state_dir)
    if dependency_bundle.account_registry is None or dependency_bundle.client_wrapper is None:
        raise RuntimeError(
            "Managed-account inbound listening requires the Telethon capability backend and valid Telegram API credentials."
        )

    available, error = dependency_bundle.client_wrapper.is_available()
    if not available:
        raise RuntimeError(error)

    campaigns_root = _resolve_telegram_data_dir() / "campaigns"
    engagement_store = dependency_bundle.engagement_store or ManagedAccountEngagementStore(_resolve_telegram_data_dir())
    conversation_projector = ExternalConversationProjector(
        ExternalConversationManager(campaigns_root),
        signal_bridge=_build_campaign_signal_bridge(
            campaigns_root,
            campaign_manager=CampaignManager(campaigns_root),
            schedule_manager=ScheduleManager(campaigns_root),
        ),
    )
    return ManagedAccountEventListener(
        dependency_bundle.account_registry,
        dependency_bundle.client_wrapper,
        engagement_store,
        conversation_projector,
    )


def create_live_execution_runner(state_dir: str | Path | None = None) -> LiveExecutionRunner:
    """Build the dedicated live execution worker for queued managed-account actions."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    components = build_runtime_components(runtime_state_dir)
    campaigns_root = _resolve_telegram_data_dir() / "campaigns"
    policy_state_manager = LiveExecutionPolicyStateManager(_resolve_telegram_data_dir())
    engagement_policy_service = CampaignEngagementPolicyService(CampaignEngagementPolicyManager(campaigns_root))
    qualification_service = QualificationService(
        components.campaign_manager,
        QualificationManager(campaigns_root),
        ExternalConversationManager(campaigns_root),
        signal_bridge=_build_campaign_signal_bridge(
            campaigns_root,
            campaign_manager=components.campaign_manager,
            work_item_manager=components.work_item_manager,
            schedule_manager=components.schedule_manager,
        ),
    )
    service = LiveExecutionService(
        LiveExecutionManager(campaigns_root),
        membership_capability=components.dependency_bundle.membership_capability,
        messaging_capability=components.dependency_bundle.messaging_capability,
        conversation_manager=ExternalConversationManager(campaigns_root),
        campaign_manager=components.campaign_manager,
        account_registry=components.dependency_bundle.account_registry,
        policy_state_manager=policy_state_manager,
        qualification_service=qualification_service,
        engagement_policy_service=engagement_policy_service,
        signal_bridge=_build_campaign_signal_bridge(
            campaigns_root,
            campaign_manager=components.campaign_manager,
            work_item_manager=components.work_item_manager,
            schedule_manager=components.schedule_manager,
        ),
        claim_ttl_seconds=int(
            os.getenv(
                "TELEGRAM_LIVE_EXECUTION_CLAIM_TTL_SECONDS",
                str(DEFAULT_LIVE_EXECUTION_CLAIM_TTL_SECONDS),
            )
        ),
    )
    return LiveExecutionRunner(
        service,
        poll_interval_seconds=float(
            os.getenv(
                "TELEGRAM_LIVE_EXECUTION_POLL_INTERVAL_SECONDS",
                str(DEFAULT_LIVE_EXECUTION_POLL_INTERVAL_SECONDS),
            )
        ),
    )


def create_conversation_review_runner(state_dir: str | Path | None = None) -> ConversationReviewRunner:
    """Build the dedicated conversation-review worker for persisted live moments."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    components = build_runtime_components(runtime_state_dir)
    campaigns_root = _resolve_telegram_data_dir() / "campaigns"
    dependency_bundle = components.dependency_bundle
    conversation_manager = ExternalConversationManager(campaigns_root)
    engagement_store = dependency_bundle.engagement_store or ManagedAccountEngagementStore(_resolve_telegram_data_dir())
    autonomous_send_manager = AutonomousSendManager(campaigns_root)
    control_manager = LiveOpsControlManager(campaigns_root)
    policy_state_manager = LiveExecutionPolicyStateManager(_resolve_telegram_data_dir())
    engagement_policy_service = CampaignEngagementPolicyService(CampaignEngagementPolicyManager(campaigns_root))
    qualification_service = QualificationService(
        components.campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
        signal_bridge=_build_campaign_signal_bridge(
            campaigns_root,
            campaign_manager=components.campaign_manager,
            work_item_manager=components.work_item_manager,
            schedule_manager=components.schedule_manager,
        ),
    )
    live_execution_service = LiveExecutionService(
        LiveExecutionManager(campaigns_root),
        conversation_manager=conversation_manager,
        campaign_manager=components.campaign_manager,
        account_registry=dependency_bundle.account_registry,
        policy_state_manager=policy_state_manager,
        qualification_service=qualification_service,
        engagement_policy_service=engagement_policy_service,
        claim_ttl_seconds=int(
            os.getenv(
                "TELEGRAM_LIVE_EXECUTION_CLAIM_TTL_SECONDS",
                str(DEFAULT_LIVE_EXECUTION_CLAIM_TTL_SECONDS),
            )
        ),
    )
    context_builder = EngagementBrainContextBuilder(
        components.campaign_manager,
        conversation_manager,
        engagement_store,
        policy_state_manager=policy_state_manager,
        autonomous_send_manager=autonomous_send_manager,
        live_ops_control_manager=control_manager,
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        AutonomousSendService(
            autonomous_send_manager,
            conversation_manager=conversation_manager,
            live_execution_service=live_execution_service,
        ),
        qualification_service,
        brain_service=EngagementBrainService(draft_generator=AnthropicDraftTextGenerator()),
        compiled_intent_store=components.compiled_intent_store,
        compiled_intent_applicator=components.compiled_intent_applicator,
        engagement_policy_service=engagement_policy_service,
    )
    triage_service = CheapInboundTriageService(
        context_builder,
        conversation_manager,
        signal_bridge=_build_campaign_signal_bridge(
            campaigns_root,
            campaign_manager=components.campaign_manager,
            work_item_manager=components.work_item_manager,
            schedule_manager=components.schedule_manager,
        ),
    )
    dispatcher = ConversationReviewDispatcher(
        conversation_manager,
        coordinator,
        conversation_timing_service=ExternalConversationTimingService(
            conversation_manager,
            engagement_policy_service=engagement_policy_service,
        ),
        triage_service=triage_service,
        claim_ttl_seconds=int(
            os.getenv(
                "TELEGRAM_CONVERSATION_REVIEW_CLAIM_TTL_SECONDS",
                str(DEFAULT_CONVERSATION_REVIEW_CLAIM_TTL_SECONDS),
            )
        ),
    )
    return ConversationReviewRunner(
        dispatcher,
        poll_interval_seconds=float(
            os.getenv(
                "TELEGRAM_CONVERSATION_REVIEW_POLL_INTERVAL_SECONDS",
                str(DEFAULT_CONVERSATION_REVIEW_POLL_INTERVAL_SECONDS),
            )
        ),
    )


def build_app() -> FastAPI:
    """Create the FastAPI app for Telegram runtime and legacy agency routes."""
    components = build_runtime_components()
    app = FastAPI(title="TelegramSwarm Runtime")
    app.state.telegram_service = create_telegram_app_service()
    app.state.telegram_bot_client = _create_telegram_bot_client()
    app.state.runtime_monitor = components.monitor
    app.state.monitoring_store = components.monitoring_store
    app.state.monitoring_jsonl_path = components.monitoring_jsonl_path
    app.state.monitoring_api_key = os.getenv("TG_SWARM_MONITORING_API_KEY", "").strip()
    app.state.monitoring_thresholds = _load_monitoring_thresholds()

    @app.get("/healthz")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def telegram_webhook(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        service: TelegramAppService = request.app.state.telegram_service
        bot_client: TelegramBotApiClient | None = request.app.state.telegram_bot_client
        update = TelegramUpdate.from_payload(payload)
        response = service.handle_update(update)
        delivery = await _deliver_telegram_response(
            bot_client,
            response,
            monitor=service.monitor,
        )
        return {
            **_telegram_response_to_dict(response),
            "delivery": delivery,
        }

    @app.get("/telegram/me")
    async def telegram_me(request: Request) -> dict[str, Any]:
        bot_client = _require_telegram_bot_client(request)
        return await bot_client.get_me()

    @app.get("/telegram/webhook/info")
    async def telegram_webhook_info(request: Request) -> dict[str, Any]:
        bot_client = _require_telegram_bot_client(request)
        return await bot_client.get_webhook_info()

    @app.post("/telegram/webhook/set")
    async def telegram_set_webhook(payload: WebhookRequest, request: Request) -> dict[str, Any]:
        bot_client = _require_telegram_bot_client(request)
        return await bot_client.set_webhook(payload.webhook_url)

    @app.post("/telegram/webhook/delete")
    async def telegram_delete_webhook(request: Request) -> dict[str, Any]:
        bot_client = _require_telegram_bot_client(request)
        return await bot_client.delete_webhook()

    @app.get("/ops/monitoring/status")
    async def monitoring_status(request: Request) -> dict[str, Any]:
        store = _require_monitoring_access(request)
        thresholds = _require_monitoring_thresholds(request)
        health = store.build_health_report(hours=1, thresholds=thresholds)
        summary = health["summary"]
        return {
            "status": health["status"],
            "auth_enabled": bool(request.app.state.monitoring_api_key),
            "sqlite_path": str(store.path),
            "jsonl_path": str(request.app.state.monitoring_jsonl_path),
            "latest_event_at": summary["latest_event_at"],
            "latest_event_age_seconds": summary["latest_event_age_seconds"],
            "events_last_hour": summary["total_events"],
            "failed_events_last_hour": summary["failed_events"],
            "failure_rate_last_hour": summary["failure_rate"],
            "alerts": health["alerts"],
        }

    @app.get("/ops/monitoring/summary")
    async def monitoring_summary(request: Request, hours: int = DEFAULT_MONITORING_SUMMARY_HOURS) -> dict[str, Any]:
        store = _require_monitoring_access(request)
        return store.build_summary(hours=hours)

    @app.get("/ops/monitoring/alerts")
    async def monitoring_alerts(request: Request, hours: int = DEFAULT_MONITORING_SUMMARY_HOURS) -> dict[str, Any]:
        store = _require_monitoring_access(request)
        thresholds = _require_monitoring_thresholds(request)
        return store.build_health_report(hours=hours, thresholds=thresholds)

    @app.get("/ops/monitoring/events")
    async def monitoring_events(
        request: Request,
        component: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        chat_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        campaign_id: str | None = None,
        workflow_stage: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        store = _require_monitoring_access(request)
        parsed_since = _parse_monitoring_since(since)
        events = store.list_events(
            component=component,
            event_type=event_type,
            trace_id=trace_id,
            chat_id=chat_id,
            user_id=user_id,
            session_id=session_id,
            campaign_id=campaign_id,
            workflow_stage=workflow_stage,
            since=parsed_since,
            limit=limit,
        )
        return {
            "count": len(events),
            "events": events,
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def monitoring_metrics(request: Request, hours: int = DEFAULT_MONITORING_SUMMARY_HOURS) -> str:
        store = _require_monitoring_access(request)
        thresholds = _require_monitoring_thresholds(request)
        return store.render_prometheus_metrics(hours=hours, thresholds=thresholds)

    return app


def _create_telegram_bot_client() -> TelegramBotApiClient | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Telegram outbound delivery will be disabled.")
        return None
    return TelegramBotApiClient(bot_token=token)


def _require_telegram_bot_client(request: Request) -> TelegramBotApiClient:
    bot_client: TelegramBotApiClient | None = request.app.state.telegram_bot_client
    if bot_client is None:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured.")
    return bot_client


async def _deliver_telegram_response(
    bot_client: TelegramBotApiClient | None,
    response: TelegramResponse,
    *,
    monitor: RuntimeEventLogger | None = None,
) -> dict[str, Any]:
    """Send outbound messages to Telegram when a bot token is configured."""
    runtime_monitor = monitor or NullRuntimeEventLogger()
    trace_context = RuntimeTraceContext(
        trace_id=str(response.metadata.get("trace_id", "")).strip(),
        chat_id=response.chat_id,
    )
    if bot_client is None:
        runtime_monitor.record_event(
            component="telegram_transport",
            event_type="delivery_skipped",
            trace_context=trace_context,
            payload={"reason": "telegram_bot_token_missing", "message_count": len(response.messages)},
        )
        return {"sent": False, "reason": "telegram_bot_token_missing"}

    sent_messages: list[dict[str, Any]] = []
    try:
        for message in response.messages:
            telegram_result = await bot_client.send_message(
                chat_id=response.chat_id,
                text=message.text,
                reply_markup=message.reply_markup,
            )
            sent_messages.append(telegram_result)
    except Exception as exc:
        runtime_monitor.record_event(
            component="telegram_transport",
            event_type="delivery_failed",
            trace_context=trace_context,
            payload={
                "error": str(exc),
                "error_type": type(exc).__name__,
                "sent_count_before_failure": len(sent_messages),
                "message_count": len(response.messages),
            },
        )
        raise

    runtime_monitor.record_event(
        component="telegram_transport",
        event_type="delivery_completed",
        trace_context=trace_context,
        payload={
            "message_count": len(response.messages),
            "messages": [message.text for message in response.messages],
        },
    )

    return {
        "sent": True,
        "count": len(sent_messages),
        "results": sent_messages,
    }


def _resolve_telegram_state_dir(state_dir: str | Path | None) -> Path:
    configured_dir = state_dir or os.getenv("TELEGRAM_RUNTIME_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir)
    return DEFAULT_TELEGRAM_STATE_DIR


def _resolve_monitoring_dir(runtime_state_dir: Path) -> Path:
    configured_dir = os.getenv("TG_SWARM_MONITORING_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir)
    return runtime_state_dir / "monitoring"


def _build_runtime_monitor(
    runtime_state_dir: Path,
) -> tuple[RuntimeEventLogger, SqliteRuntimeMonitoringStore, Path]:
    monitoring_dir = _resolve_monitoring_dir(runtime_state_dir)
    monitoring_store = SqliteRuntimeMonitoringStore(monitoring_dir / "runtime_events.sqlite3")
    monitoring_jsonl_path = monitoring_dir / "runtime_events.jsonl"
    monitor = FanoutRuntimeEventLogger(
        [
            JsonlRuntimeEventLogger(monitoring_jsonl_path),
            monitoring_store,
        ]
    )
    return monitor, monitoring_store, monitoring_jsonl_path


def _require_monitoring_access(request: Request) -> SqliteRuntimeMonitoringStore:
    configured_key = str(getattr(request.app.state, "monitoring_api_key", "") or "").strip()
    if configured_key:
        header_key = request.headers.get("x-monitoring-key", "").strip()
        authorization = request.headers.get("authorization", "").strip()
        bearer_key = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
        if header_key != configured_key and bearer_key != configured_key:
            raise HTTPException(status_code=401, detail="Monitoring access is not authorized.")

    store: SqliteRuntimeMonitoringStore | None = getattr(request.app.state, "monitoring_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Monitoring store is not available in this runtime.")
    return store


def _require_monitoring_thresholds(request: Request) -> RuntimeMonitoringThresholds:
    thresholds: RuntimeMonitoringThresholds | None = getattr(request.app.state, "monitoring_thresholds", None)
    if thresholds is None:
        return RuntimeMonitoringThresholds()
    return thresholds


def _load_monitoring_thresholds() -> RuntimeMonitoringThresholds:
    return RuntimeMonitoringThresholds(
        max_failed_events=_read_env_int("TG_SWARM_MONITORING_MAX_FAILED_EVENTS", default=5, minimum=0),
        max_failure_rate=_read_env_float("TG_SWARM_MONITORING_MAX_FAILURE_RATE", default=0.2, minimum=0.0),
        max_delivery_failures=_read_env_int("TG_SWARM_MONITORING_MAX_DELIVERY_FAILURES", default=2, minimum=0),
        max_turn_failures=_read_env_int("TG_SWARM_MONITORING_MAX_TURN_FAILURES", default=1, minimum=0),
        max_event_age_seconds=_read_env_int("TG_SWARM_MONITORING_MAX_EVENT_AGE_SECONDS", default=900, minimum=1),
    )


def _parse_monitoring_since(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="`since` must be a valid ISO-8601 timestamp.") from exc


def _read_env_int(name: str, *, default: int, minimum: int | None = None) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning("%s=%r is not a valid integer. Falling back to %s.", name, raw_value, default)
        return default
    if minimum is not None and parsed < minimum:
        logger.warning("%s=%r is below the allowed minimum %s. Falling back to %s.", name, raw_value, minimum, default)
        return default
    return parsed


def _read_env_float(name: str, *, default: float, minimum: float | None = None) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning("%s=%r is not a valid float. Falling back to %s.", name, raw_value, default)
        return default
    if minimum is not None and parsed < minimum:
        logger.warning("%s=%r is below the allowed minimum %s. Falling back to %s.", name, raw_value, minimum, default)
        return default
    return parsed


def _build_campaign_signal_bridge(
    campaigns_root: Path,
    *,
    campaign_manager: CampaignManager | None = None,
    work_item_manager: WorkItemManager | None = None,
    schedule_manager: ScheduleManager | None = None,
) -> CampaignSignalBridge:
    resolved_campaign_manager = campaign_manager or CampaignManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    resolved_work_item_manager = work_item_manager or WorkItemManager(campaigns_root)
    resolved_schedule_manager = schedule_manager or ScheduleManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        resolved_campaign_manager,
        resolved_work_item_manager,
        resolved_schedule_manager,
        signal_manager,
        conversation_manager=ExternalConversationManager(campaigns_root),
        intervention_manager=OperatorInterventionManager(
            resolved_campaign_manager,
            resolved_schedule_manager,
            signal_manager,
        ),
    )
    return CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, resolved_work_item_manager),
        continuous_ops_manager=continuous_ops_manager,
    )


def _build_runtime_dependency_bundle(runtime_state_dir: Path) -> RuntimeDependencyBundle:
    backend = _resolve_capability_backend()
    if backend == "telethon":
        return _build_telethon_dependency_bundle(runtime_state_dir)
    if backend != DEFAULT_CAPABILITY_BACKEND:
        logger.warning(
            "Unknown TELEGRAM_CAPABILITY_BACKEND=%r. Falling back to %s.",
            backend,
            DEFAULT_CAPABILITY_BACKEND,
        )
    return _build_stub_dependency_bundle()


def _build_stub_dependency_bundle() -> RuntimeDependencyBundle:
    account_capability = StubAccountCapability()
    return RuntimeDependencyBundle(
        account_capability=account_capability,
        community_capability=StubCommunityCapability(),
        membership_capability=StubMembershipCapability(),
        messaging_capability=StubMessagingCapability(),
    )


def _build_telethon_dependency_bundle(runtime_state_dir: Path) -> RuntimeDependencyBundle:
    data_dir = _resolve_telegram_data_dir()
    registry = AccountRegistry(data_dir / "accounts.json")
    client_wrapper = TelethonClientWrapper(
        api_id=_resolve_telegram_api_id(),
        api_hash=os.getenv("TELEGRAM_API_HASH", "").strip(),
        session_manager=TelethonSessionManager(data_dir / "sessions"),
    )
    audit_logger = JsonlAuditLogger(data_dir / "audit" / "telegram_actions.jsonl")
    engagement_store = ManagedAccountEngagementStore(data_dir)
    account_capability = AccountCapabilityImpl(registry)
    auth_manager = AuthManager(
        JsonAuthStateStore(runtime_state_dir / "auth_states.json"),
        registry=registry if _telethon_auth_is_configured(client_wrapper) else None,
        gateway=TelethonAuthGateway(client_wrapper) if _telethon_auth_is_configured(client_wrapper) else None,
    )
    logger.info("Using Telethon-backed Telegram capability layer from %s", data_dir)
    return RuntimeDependencyBundle(
        auth_manager=auth_manager,
        account_registry=registry,
        account_capability=account_capability,
        client_wrapper=client_wrapper,
        community_capability=CommunityCapabilityImpl(registry, client_wrapper),
        engagement_store=engagement_store,
        membership_capability=MembershipCapabilityImpl(
            registry,
            client_wrapper,
            audit_logger=audit_logger,
        ),
        messaging_capability=MessagingCapabilityImpl(
            registry,
            client_wrapper,
            audit_logger=audit_logger,
            engagement_store=engagement_store,
        ),
    )


def _resolve_capability_backend() -> str:
    return os.getenv("TELEGRAM_CAPABILITY_BACKEND", DEFAULT_CAPABILITY_BACKEND).strip().lower()


def _resolve_telegram_data_dir() -> Path:
    configured_dir = os.getenv("TG_SWARM_DATA_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir)
    return DEFAULT_TELEGRAM_DATA_DIR


def _resolve_telegram_api_id() -> int | None:
    raw_value = os.getenv("TELEGRAM_API_ID", "").strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError:
        logger.warning("TELEGRAM_API_ID=%r is not a valid integer. Telethon auth will stay unavailable.", raw_value)
        return None


def _telethon_auth_is_configured(client_wrapper: TelethonClientWrapper) -> bool:
    available, _error = client_wrapper.is_available()
    return available


def _telegram_response_to_dict(response: TelegramResponse) -> dict[str, Any]:
    """Convert the runtime response dataclass into a JSON-safe dict."""
    return {
        "ok": True,
        "chat_id": response.chat_id,
        "messages": [asdict(message) for message in response.messages],
    }


app = build_app()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the TelegramSwarm runtime.")
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Run local Telegram long polling instead of the FastAPI server.",
    )
    parser.add_argument(
        "--run-engagement-listener",
        action="store_true",
        help="Run the dedicated managed-account inbound listener worker instead of the FastAPI server.",
    )
    parser.add_argument(
        "--run-scheduler",
        action="store_true",
        help="Run the dedicated scheduled-work worker instead of the FastAPI server.",
    )
    parser.add_argument(
        "--run-live-executor",
        action="store_true",
        help="Run the dedicated live execution worker instead of the FastAPI server.",
    )
    parser.add_argument(
        "--run-conversation-reviewer",
        action="store_true",
        help="Run the dedicated conversation-review worker instead of the FastAPI server.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    runtime_state_dir = _resolve_telegram_state_dir(None)

    if args.run_scheduler:
        logger.info("Starting TelegramSwarm scheduled-work runner.")
        create_scheduled_work_runner(runtime_state_dir).run_forever()
    elif args.run_engagement_listener:
        logger.info("Starting TelegramSwarm managed-account inbound listener.")
        create_managed_account_event_listener(runtime_state_dir).run_forever()
    elif args.run_live_executor:
        logger.info("Starting TelegramSwarm live execution runner.")
        create_live_execution_runner(runtime_state_dir).run_forever()
    elif args.run_conversation_reviewer:
        logger.info("Starting TelegramSwarm conversation review runner.")
        create_conversation_review_runner(runtime_state_dir).run_forever()
    elif args.poll:
        bot_client = _create_telegram_bot_client()
        if bot_client is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for polling mode.")
        logger.info("Starting TelegramSwarm in local polling mode.")
        asyncio.run(
            run_telegram_polling(
                service=create_telegram_app_service(runtime_state_dir),
                bot_client=bot_client,
                cursor_store=JsonTelegramPollingCursorStore(runtime_state_dir / "polling_cursor.json"),
            )
        )
    else:
        logger.info("Starting TelegramSwarm runtime at http://%s:%s", host, port)
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
