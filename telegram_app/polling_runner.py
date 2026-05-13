"""Long-polling runner for local Telegram bot testing without webhooks."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram_app.app_service import TelegramAppService
from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.monitoring import RuntimeTraceContext
from telegram_app.transport import TelegramBotApiClient, TelegramUpdate

logger = logging.getLogger(__name__)
DEFAULT_POLL_RETRY_DELAY_SECONDS = 3.0
POLLING_CURSOR_DEFAULT_PAYLOAD = {"last_processed_update_id": None}


class JsonTelegramPollingCursorStore:
    """Persist the last delivered Telegram update id across polling restarts."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)

    def load_last_processed_update_id(self) -> int | None:
        payload = load_json_file(self._file_path, default=POLLING_CURSOR_DEFAULT_PAYLOAD)
        update_id = payload.get("last_processed_update_id")
        return update_id if isinstance(update_id, int) else None

    def save_last_processed_update_id(self, update_id: int) -> None:
        write_json_file(self._file_path, {"last_processed_update_id": update_id})


class TelegramPollingRunner:
    """Run the Telegram runtime over Bot API long polling."""

    def __init__(
        self,
        service: TelegramAppService,
        bot_client: TelegramBotApiClient,
        poll_timeout_seconds: int = 30,
        retry_delay_seconds: float = DEFAULT_POLL_RETRY_DELAY_SECONDS,
        cursor_store: JsonTelegramPollingCursorStore | None = None,
    ) -> None:
        self._service = service
        self._bot_client = bot_client
        self._poll_timeout_seconds = poll_timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._cursor_store = cursor_store
        self._last_processed_update_id = (
            self._cursor_store.load_last_processed_update_id()
            if self._cursor_store is not None
            else None
        )
        self._next_offset = (
            self._last_processed_update_id + 1
            if self._last_processed_update_id is not None
            else None
        )

    async def run_forever(self) -> None:
        """Poll Telegram for updates and process them continuously."""
        logger.info("Starting Telegram long polling.")
        await self._delete_webhook_with_retry()

        while True:
            try:
                response = await self._bot_client.get_updates(
                    offset=self._next_offset,
                    timeout=self._poll_timeout_seconds,
                    allowed_updates=["message"],
                )
            except Exception:
                logger.exception(
                    "Telegram getUpdates failed. Retrying in %.1f seconds.",
                    self._retry_delay_seconds,
                )
                await asyncio.sleep(self._retry_delay_seconds)
                continue
            for update_payload in response.get("result", []):
                try:
                    await self._handle_update(update_payload)
                except Exception:
                    logger.exception("Failed to process Telegram update payload: %s", update_payload)
                    break

    async def _delete_webhook_with_retry(self) -> None:
        while True:
            try:
                await self._bot_client.delete_webhook(drop_pending_updates=False)
                return
            except Exception:
                logger.exception(
                    "Telegram deleteWebhook failed before polling start. Retrying in %.1f seconds.",
                    self._retry_delay_seconds,
                )
                await asyncio.sleep(self._retry_delay_seconds)

    async def _handle_update(self, payload: dict[str, object]) -> None:
        update_id = payload.get("update_id")
        if self._is_already_processed(update_id):
            logger.info("Skipping already-processed Telegram update: update_id=%s", update_id)
            self._advance_offset(update_id)
            return

        update = TelegramUpdate.from_payload(payload)
        if not update.chat_id or not update.text:
            logger.debug("Skipping unsupported Telegram update payload: %s", payload)
            self._mark_update_processed(update_id)
            return

        logger.info(
            "Received Telegram update: update_id=%s chat_id=%s user_id=%s text=%r",
            update_id,
            update.chat_id,
            update.user_id,
            update.text,
        )

        response = self._service.handle_update(update)
        trace_id = str(response.metadata.get("trace_id", "")).strip()
        for message in response.messages:
            logger.info(
                "Sending Telegram message: chat_id=%s text=%r",
                response.chat_id,
                message.text,
            )
            await self._bot_client.send_message(
                chat_id=response.chat_id,
                text=message.text,
                reply_markup=message.reply_markup,
            )
        self._service.monitor.record_event(
            component="telegram_transport",
            event_type="delivery_completed",
            trace_context=RuntimeTraceContext(trace_id=trace_id, chat_id=response.chat_id),
            payload={
                "message_count": len(response.messages),
                "messages": [message.text for message in response.messages],
            },
        )
        self._mark_update_processed(update_id)

    def _is_already_processed(self, update_id: object) -> bool:
        return (
            isinstance(update_id, int)
            and self._last_processed_update_id is not None
            and update_id <= self._last_processed_update_id
        )

    def _mark_update_processed(self, update_id: object) -> None:
        self._advance_offset(update_id)
        if not isinstance(update_id, int):
            return
        self._last_processed_update_id = update_id
        if self._cursor_store is not None:
            self._cursor_store.save_last_processed_update_id(update_id)

    def _advance_offset(self, update_id: object) -> None:
        if not isinstance(update_id, int):
            return
        next_offset = update_id + 1
        if self._next_offset is None or next_offset > self._next_offset:
            self._next_offset = next_offset


async def run_telegram_polling(
    service: TelegramAppService,
    bot_client: TelegramBotApiClient,
    poll_timeout_seconds: int = 30,
    cursor_store: JsonTelegramPollingCursorStore | None = None,
) -> None:
    """Convenience entrypoint for local polling mode."""
    runner = TelegramPollingRunner(
        service=service,
        bot_client=bot_client,
        poll_timeout_seconds=poll_timeout_seconds,
        cursor_store=cursor_store,
    )
    await runner.run_forever()
