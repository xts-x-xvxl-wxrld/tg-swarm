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
from pydantic import BaseModel, Field
import uvicorn

from telegram_app import TelegramAppService, run_telegram_polling
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
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.intake import StructuredIntakeCoordinator
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

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_STATE_DIR = Path("activity-logs") / "telegram-runtime"
DEFAULT_TELEGRAM_DATA_DIR = Path("data")
DEFAULT_CAPABILITY_BACKEND = "stub"
DEFAULT_SCHEDULER_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_SCHEDULER_LEASE_TTL_SECONDS = 30


@dataclass(slots=True)
class RuntimeDependencyBundle:
    """Compose startup-time runtime dependencies."""

    auth_manager: AuthManager | None = None
    account_capability: AccountCapability | None = None
    community_capability: CommunityCapability | None = None
    membership_capability: MembershipCapability | None = None
    messaging_capability: MessagingCapability | None = None


@dataclass(slots=True)
class TelegramRuntimeComponents:
    """Shared runtime objects reused by interactive and scheduler entrypoints."""

    campaign_manager: CampaignManager
    work_item_manager: WorkItemManager
    schedule_manager: ScheduleManager
    session_manager: SessionManager
    approval_manager: ApprovalManager
    orchestrator: PurposeBuiltOrchestrator
    dependency_bundle: RuntimeDependencyBundle


class WebhookRequest(BaseModel):
    webhook_url: str = Field(..., description="Public HTTPS webhook URL for Telegram callbacks.")


def create_telegram_app_service(state_dir: str | Path | None = None) -> TelegramAppService:
    """Build the thin Telegram runtime service with persistent local state."""
    components = build_runtime_components(state_dir)
    intake_coordinator = StructuredIntakeCoordinator(components.session_manager)
    return TelegramAppService(
        session_manager=components.session_manager,
        approval_manager=components.approval_manager,
        orchestrator=components.orchestrator,
        intake_coordinator=intake_coordinator,
        auth_manager=components.dependency_bundle.auth_manager,
        account_capability=components.dependency_bundle.account_capability,
        campaign_manager=components.campaign_manager,
    )


def build_runtime_components(state_dir: str | Path | None = None) -> TelegramRuntimeComponents:
    """Compose the reusable runtime objects behind both app and scheduler entrypoints."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    campaigns_root = _resolve_telegram_data_dir() / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    session_manager = SessionManager(JsonSessionStore(runtime_state_dir / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(runtime_state_dir / "approvals.json"))
    dependency_bundle = _build_runtime_dependency_bundle(runtime_state_dir)
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
    )
    return TelegramRuntimeComponents(
        campaign_manager=campaign_manager,
        work_item_manager=work_item_manager,
        schedule_manager=schedule_manager,
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
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


def build_app() -> FastAPI:
    """Create the FastAPI app for Telegram runtime and legacy agency routes."""
    app = FastAPI(title="TelegramSwarm Runtime")
    app.state.telegram_service = create_telegram_app_service()
    app.state.telegram_bot_client = _create_telegram_bot_client()

    @app.get("/healthz")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def telegram_webhook(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        service: TelegramAppService = request.app.state.telegram_service
        bot_client: TelegramBotApiClient | None = request.app.state.telegram_bot_client
        update = TelegramUpdate.from_payload(payload)
        response = service.handle_update(update)
        delivery = await _deliver_telegram_response(bot_client, response)
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
) -> dict[str, Any]:
    """Send outbound messages to Telegram when a bot token is configured."""
    if bot_client is None:
        return {"sent": False, "reason": "telegram_bot_token_missing"}

    sent_messages: list[dict[str, Any]] = []
    for message in response.messages:
        telegram_result = await bot_client.send_message(
            chat_id=response.chat_id,
            text=message.text,
            reply_markup=message.reply_markup,
        )
        sent_messages.append(telegram_result)

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
    account_capability = AccountCapabilityImpl(registry)
    auth_manager = AuthManager(
        JsonAuthStateStore(runtime_state_dir / "auth_states.json"),
        registry=registry if _telethon_auth_is_configured(client_wrapper) else None,
        gateway=TelethonAuthGateway(client_wrapper) if _telethon_auth_is_configured(client_wrapper) else None,
    )
    logger.info("Using Telethon-backed Telegram capability layer from %s", data_dir)
    return RuntimeDependencyBundle(
        auth_manager=auth_manager,
        account_capability=account_capability,
        community_capability=CommunityCapabilityImpl(registry, client_wrapper),
        membership_capability=MembershipCapabilityImpl(
            registry,
            client_wrapper,
            audit_logger=audit_logger,
        ),
        messaging_capability=MessagingCapabilityImpl(
            registry,
            client_wrapper,
            audit_logger=audit_logger,
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
        "--run-scheduler",
        action="store_true",
        help="Run the dedicated scheduled-work worker instead of the FastAPI server.",
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
