"""Minimal Telegram Bot API client for outbound messaging and webhook setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .formatting import TELEGRAM_BOT_PARSE_MODE, format_telegram_html


@dataclass(slots=True)
class TelegramBotApiClient:
    """Small async wrapper around the Telegram Bot API."""

    bot_token: str
    timeout_seconds: float = 15.0

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": format_telegram_html(text),
            "parse_mode": TELEGRAM_BOT_PARSE_MODE,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._post("sendMessage", payload)

    async def set_webhook(self, webhook_url: str) -> dict[str, Any]:
        return await self._post("setWebhook", {"url": webhook_url})

    async def delete_webhook(self, drop_pending_updates: bool = False) -> dict[str, Any]:
        return await self._post(
            "deleteWebhook",
            {"drop_pending_updates": drop_pending_updates},
        )

    async def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 30,
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        # Long polling can legitimately wait as long as the Telegram timeout.
        # Give the HTTP client a little extra time so an empty poll does not crash the runner.
        return await self._post("getUpdates", payload, timeout_seconds=timeout + 10)

    async def get_webhook_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/getWebhookInfo")
            response.raise_for_status()
            return response.json()

    async def get_me(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/getMe")
            response.raise_for_status()
            return response.json()

    async def _post(
        self,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_seconds or self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)
            response.raise_for_status()
            return response.json()
