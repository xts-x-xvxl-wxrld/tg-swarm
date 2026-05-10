# FastAPI entry point for the Telegram-native runtime and legacy agency API.

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
import uvicorn

from telegram_app import TelegramAppService, run_telegram_polling
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramBotApiClient, TelegramResponse, TelegramUpdate

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_STATE_DIR = Path("activity-logs") / "telegram-runtime"


class WebhookRequest(BaseModel):
    webhook_url: str = Field(..., description="Public HTTPS webhook URL for Telegram callbacks.")


def create_telegram_app_service(state_dir: str | Path | None = None) -> TelegramAppService:
    """Build the thin Telegram runtime service with persistent local state."""
    runtime_state_dir = _resolve_telegram_state_dir(state_dir)
    session_manager = SessionManager(
        JsonSessionStore(runtime_state_dir / "sessions.json")
    )
    approval_manager = ApprovalManager(
        JsonApprovalStore(runtime_state_dir / "approvals.json")
    )
    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        approval_manager=approval_manager,
    )
    intake_coordinator = StructuredIntakeCoordinator(session_manager)
    return TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
        intake_coordinator=intake_coordinator,
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
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))

    if args.poll:
        bot_client = _create_telegram_bot_client()
        if bot_client is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for polling mode.")
        logger.info("Starting TelegramSwarm in local polling mode.")
        asyncio.run(
            run_telegram_polling(
                service=create_telegram_app_service(),
                bot_client=bot_client,
            )
        )
    else:
        logger.info("Starting TelegramSwarm runtime at http://%s:%s", host, port)
        uvicorn.run(app, host=host, port=port)
