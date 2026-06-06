"""Normalized inbound Telegram update models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from telegram_app.models import CampaignAssetKind


@dataclass(slots=True)
class TelegramAttachment:
    """Normalized Telegram attachment metadata."""

    attachment_id: str
    kind: CampaignAssetKind
    telegram_file_id: str
    telegram_file_unique_id: str = ""
    telegram_message_id: str = ""
    file_name: str = ""
    mime_type: str = ""
    caption: str = ""
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the attachment for debugging or tests."""
        return {
            "attachment_id": self.attachment_id,
            "kind": self.kind.value,
            "telegram_file_id": self.telegram_file_id,
            "telegram_file_unique_id": self.telegram_file_unique_id,
            "telegram_message_id": self.telegram_message_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "caption": self.caption,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
        }


@dataclass(slots=True)
class TelegramUpdate:
    """Normalized subset of a Telegram update used by the runtime."""

    chat_id: str
    user_id: str
    text: str
    command: str | None = None
    message_id: str = ""
    attachments: list[TelegramAttachment] = field(default_factory=list)
    raw_update: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TelegramUpdate":
        """Create an update from a Telegram-like payload."""
        message = payload.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})
        text = message.get("text", "") or message.get("caption", "") or ""
        command = text.split(maxsplit=1)[0] if text.startswith("/") else None
        return cls(
            chat_id=str(chat.get("id", "")),
            user_id=str(sender.get("id", "")),
            text=text,
            command=command,
            message_id=str(message.get("message_id", "")),
            attachments=_extract_attachments(message),
            raw_update=payload,
        )


def _extract_attachments(message: dict[str, Any]) -> list[TelegramAttachment]:
    attachments: list[TelegramAttachment] = []
    caption = str(message.get("caption", "") or "")
    message_id = str(message.get("message_id", "") or "")

    document = message.get("document", {})
    if isinstance(document, dict) and str(document.get("file_id", "")).strip():
        attachments.append(
            TelegramAttachment(
                attachment_id=f"{message_id}:document:0",
                kind=CampaignAssetKind.DOCUMENT,
                telegram_file_id=str(document.get("file_id", "")),
                telegram_file_unique_id=str(document.get("file_unique_id", "")),
                telegram_message_id=message_id,
                file_name=str(document.get("file_name", "")),
                mime_type=str(document.get("mime_type", "")),
                caption=caption,
                size_bytes=int(document.get("file_size", 0) or 0),
            )
        )

    photos = message.get("photo", [])
    if isinstance(photos, list) and photos:
        chosen_photo = _select_largest_photo(photos)
        attachments.append(
            TelegramAttachment(
                attachment_id=f"{message_id}:photo:0",
                kind=CampaignAssetKind.IMAGE,
                telegram_file_id=str(chosen_photo.get("file_id", "")),
                telegram_file_unique_id=str(chosen_photo.get("file_unique_id", "")),
                telegram_message_id=message_id,
                file_name=f"photo-{message_id}.jpg" if message_id else "photo.jpg",
                mime_type="image/jpeg",
                caption=caption,
                size_bytes=int(chosen_photo.get("file_size", 0) or 0),
                width=_optional_int(chosen_photo.get("width")),
                height=_optional_int(chosen_photo.get("height")),
            )
        )
    return attachments


def _select_largest_photo(photos: list[object]) -> dict[str, Any]:
    candidate_photos = [photo for photo in photos if isinstance(photo, dict)]
    if not candidate_photos:
        return {}
    return max(
        candidate_photos,
        key=lambda photo: (
            int(photo.get("file_size", 0) or 0),
            int(photo.get("width", 0) or 0) * int(photo.get("height", 0) or 0),
        ),
    )


def _optional_int(value: object) -> int | None:
    if value in ("", None):
        return None
    return int(value)
