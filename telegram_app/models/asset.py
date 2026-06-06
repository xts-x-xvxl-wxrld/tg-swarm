"""Campaign asset records persisted under the campaign workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CampaignAssetKind(StrEnum):
    """Supported campaign asset kinds."""

    DOCUMENT = "document"
    IMAGE = "image"


class CampaignAssetRole(StrEnum):
    """Supported additive inferred roles for one campaign asset."""

    CAMPAIGN_CONTEXT = "campaign_context"
    OUTBOUND_MEDIA = "outbound_media"
    QUALIFICATION_MATERIAL = "qualification_material"
    CONVERSION_SUPPORT = "conversion_support"
    PROOF_OR_TRUST_SIGNAL = "proof_or_trust_signal"


@dataclass(slots=True)
class CampaignAssetRecord:
    """Durable metadata for one ingested campaign asset."""

    asset_id: str
    campaign_id: str
    source_session_id: str
    source_operator_id: str
    source_message_id: str
    source_attachment_id: str
    kind: CampaignAssetKind
    telegram_file_id: str = ""
    telegram_file_unique_id: str = ""
    stored_path: str = ""
    derived_text_path: str = ""
    analysis_path: str = ""
    original_file_name: str = ""
    mime_type: str = ""
    caption: str = ""
    size_bytes: int = 0
    analysis_summary: str = ""
    tags: list[str] = field(default_factory=list)
    inferred_roles: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)
    sendable: bool = False
    operator_labeled_sendable: bool = False
    ingest_status: str = "stored"
    ingest_error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the asset for JSON-backed storage."""
        return {
            "asset_id": self.asset_id,
            "campaign_id": self.campaign_id,
            "source_session_id": self.source_session_id,
            "source_operator_id": self.source_operator_id,
            "source_message_id": self.source_message_id,
            "source_attachment_id": self.source_attachment_id,
            "kind": self.kind.value,
            "telegram_file_id": self.telegram_file_id,
            "telegram_file_unique_id": self.telegram_file_unique_id,
            "stored_path": self.stored_path,
            "derived_text_path": self.derived_text_path,
            "analysis_path": self.analysis_path,
            "original_file_name": self.original_file_name,
            "mime_type": self.mime_type,
            "caption": self.caption,
            "size_bytes": self.size_bytes,
            "analysis_summary": self.analysis_summary,
            "tags": list(self.tags),
            "inferred_roles": list(self.inferred_roles),
            "uncertainty_notes": list(self.uncertainty_notes),
            "sendable": self.sendable,
            "operator_labeled_sendable": self.operator_labeled_sendable,
            "ingest_status": self.ingest_status,
            "ingest_error": self.ingest_error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignAssetRecord":
        """Hydrate a stored asset record."""
        payload = payload or {}
        raw_kind = payload.get("kind", CampaignAssetKind.DOCUMENT.value)
        kind = CampaignAssetKind._value2member_map_.get(raw_kind, CampaignAssetKind.DOCUMENT)
        tags = payload.get("tags", [])
        inferred_roles = payload.get("inferred_roles", [])
        uncertainty_notes = payload.get("uncertainty_notes", [])
        return cls(
            asset_id=str(payload.get("asset_id", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            source_session_id=str(payload.get("source_session_id", "")),
            source_operator_id=str(payload.get("source_operator_id", "")),
            source_message_id=str(payload.get("source_message_id", "")),
            source_attachment_id=str(payload.get("source_attachment_id", "")),
            kind=kind,
            telegram_file_id=str(payload.get("telegram_file_id", "")),
            telegram_file_unique_id=str(payload.get("telegram_file_unique_id", "")),
            stored_path=str(payload.get("stored_path", "")),
            derived_text_path=str(payload.get("derived_text_path", "")),
            analysis_path=str(payload.get("analysis_path", "")),
            original_file_name=str(payload.get("original_file_name", "")),
            mime_type=str(payload.get("mime_type", "")),
            caption=str(payload.get("caption", "")),
            size_bytes=int(payload.get("size_bytes", 0) or 0),
            analysis_summary=str(payload.get("analysis_summary", "")),
            tags=list(tags) if isinstance(tags, list) else [],
            inferred_roles=list(inferred_roles) if isinstance(inferred_roles, list) else [],
            uncertainty_notes=list(uncertainty_notes) if isinstance(uncertainty_notes, list) else [],
            sendable=bool(payload.get("sendable", False)),
            operator_labeled_sendable=bool(payload.get("operator_labeled_sendable", False)),
            ingest_status=str(payload.get("ingest_status", "stored")),
            ingest_error=str(payload.get("ingest_error", "")),
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
        )
