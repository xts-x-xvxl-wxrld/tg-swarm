"""Long-polling runner for local Telegram bot testing without webhooks."""

from __future__ import annotations

import asyncio
import logging

from telegram_app.app_service import TelegramAppService
from telegram_app.transport import TelegramBotApiClient, TelegramUpdate

logger = logging.getLogger(__name__)


class TelegramPollingRunner:
    """Run the Telegram runtime over Bot API long polling."""

    def __init__(
        self,
        service: TelegramAppService,
        bot_client: TelegramBotApiClient,
        poll_timeout_seconds: int = 30,
    ) -> None:
        self._service = service
        self._bot_client = bot_client
        self._poll_timeout_seconds = poll_timeout_seconds
        self._next_offset: int | None = None

    async def run_forever(self) -> None:
        """Poll Telegram for updates and process them continuously."""
        logger.info("Starting Telegram long polling.")
        await self._bot_client.delete_webhook(drop_pending_updates=False)

        while True:
            response = await self._bot_client.get_updates(
                offset=self._next_offset,
                timeout=self._poll_timeout_seconds,
                allowed_updates=["message"],
            )
            for update_payload in response.get("result", []):
                try:
                    await self._handle_update(update_payload)
                except Exception:
                    logger.exception("Failed to process Telegram update payload: %s", update_payload)

    async def _handle_update(self, payload: dict[str, object]) -> None:
        update_id = payload.get("update_id")
        if isinstance(update_id, int):
            self._next_offset = update_id + 1

        update = TelegramUpdate.from_payload(payload)
        if not update.chat_id or not update.text:
            logger.debug("Skipping unsupported Telegram update payload: %s", payload)
            return

        logger.info(
            "Received Telegram update: update_id=%s chat_id=%s user_id=%s text=%r",
            update_id,
            update.chat_id,
            update.user_id,
            update.text,
        )

        response = self._service.handle_update(update)
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


async def run_telegram_polling(
    service: TelegramAppService,
    bot_client: TelegramBotApiClient,
    poll_timeout_seconds: int = 30,
) -> None:
    """Convenience entrypoint for local polling mode."""
    runner = TelegramPollingRunner(
        service=service,
        bot_client=bot_client,
        poll_timeout_seconds=poll_timeout_seconds,
    )
    await runner.run_forever()
