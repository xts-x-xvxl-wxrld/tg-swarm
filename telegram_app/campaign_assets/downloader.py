"""Telegram attachment download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from telegram_app.transport import TelegramAttachment


@dataclass(slots=True)
class DownloadedTelegramAttachment:
    """Downloaded Telegram attachment payload."""

    content: bytes
    file_name: str
    mime_type: str


class TelegramAttachmentDownloader(Protocol):
    """Protocol for downloading Telegram attachments."""

    def download_attachment(self, attachment: TelegramAttachment) -> DownloadedTelegramAttachment:
        """Download one attachment and return the raw bytes."""


class BotApiAttachmentDownloader:
    """Download Telegram files through the Bot API using a bot token."""

    def __init__(self, bot_token: str, *, timeout_seconds: float = 30.0) -> None:
        self._bot_token = bot_token.strip()
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        """Return true when a bot token is available."""
        return bool(self._bot_token)

    def download_attachment(self, attachment: TelegramAttachment) -> DownloadedTelegramAttachment:
        """Download one Telegram attachment through `getFile`."""
        if not self.available:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured for attachment downloads.")

        base_url = f"https://api.telegram.org/bot{self._bot_token}"
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.get(f"{base_url}/getFile", params={"file_id": attachment.telegram_file_id})
            response.raise_for_status()
            payload = response.json()
            file_path = str(payload.get("result", {}).get("file_path", "")).strip()
            if not file_path:
                raise RuntimeError("Telegram getFile did not return a file_path.")

            file_response = client.get(f"https://api.telegram.org/file/bot{self._bot_token}/{file_path}")
            file_response.raise_for_status()
            file_name = attachment.file_name or Path(file_path).name or f"{attachment.kind.value}.bin"
            mime_type = attachment.mime_type or _mime_type_from_name(file_name)
            return DownloadedTelegramAttachment(
                content=file_response.content,
                file_name=file_name,
                mime_type=mime_type,
            )


def _mime_type_from_name(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".txt", ".md"}:
        return "text/plain"
    return "application/octet-stream"
