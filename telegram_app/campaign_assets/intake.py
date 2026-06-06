"""Coordinate campaign asset ingestion for one operator turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from telegram_app.campaign_assets.analyzers import AssetAnalysisResult, CampaignAssetAnalyzer
from telegram_app.campaign_assets.downloader import TelegramAttachmentDownloader
from telegram_app.campaign_assets.manager import CampaignAssetManager
from telegram_app.campaign_setup import get_campaign_setup_state, save_campaign_setup_state
from telegram_app.models import CampaignAssetRecord, SessionRecord
from telegram_app.sessions import SessionManager
from telegram_app.transport import TelegramAttachment, TelegramUpdate


@dataclass(slots=True)
class CampaignAssetTurnResult:
    """Compact result of processing campaign assets for one turn."""

    asset_refs: list[str] = field(default_factory=list)
    operator_message: str = ""
    labeling_note: str = ""
    uncertainty_notes: list[str] = field(default_factory=list)


class CampaignAssetIntakeCoordinator:
    """Persist operator-uploaded assets under the active campaign workspace."""

    def __init__(
        self,
        session_manager: SessionManager,
        *,
        downloader: TelegramAttachmentDownloader | None = None,
        asset_manager: CampaignAssetManager | None = None,
        analyzer: CampaignAssetAnalyzer | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._downloader = downloader
        self._asset_manager = asset_manager or CampaignAssetManager()
        self._analyzer = analyzer or CampaignAssetAnalyzer()

    def ingest_operator_update(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
    ) -> CampaignAssetTurnResult:
        """Ingest attachments and explicit sendable labels from one operator update."""
        result = CampaignAssetTurnResult()
        if not session.campaign_workspace_path or not session.campaign_id:
            return result

        workspace_path = Path(session.campaign_workspace_path)
        self._asset_manager.ensure_workspace(workspace_path)

        labeling_note = self._apply_explicit_label_update(workspace_path, update.text)
        if labeling_note:
            result.labeling_note = labeling_note

        if not update.attachments:
            return result

        asset_refs: list[str] = []
        uncertainty_notes: list[str] = []
        for attachment in update.attachments:
            asset = self._ingest_attachment(session, workspace_path, attachment)
            if asset is not None:
                asset_refs.append(asset.asset_id)
                for note in asset.uncertainty_notes:
                    if note not in uncertainty_notes:
                        uncertainty_notes.append(note)

        if asset_refs:
            self._merge_asset_refs_into_session(session, asset_refs)
            result.asset_refs = asset_refs
            result.uncertainty_notes = uncertainty_notes
            if not update.text.strip():
                result.operator_message = self._build_operator_message(
                    update.attachments,
                    len(asset_refs),
                    uncertainty_notes=uncertainty_notes,
                )
        return result

    def _ingest_attachment(
        self,
        session: SessionRecord,
        workspace_path: Path,
        attachment: TelegramAttachment,
    ) -> CampaignAssetRecord | None:
        existing_asset = self._asset_manager.find_existing_asset(workspace_path, attachment)
        if existing_asset is not None:
            return existing_asset
        if self._downloader is None:
            return None

        try:
            download = self._downloader.download_attachment(attachment)
        except Exception:
            return None
        asset_id = self._asset_manager.build_asset_id(attachment)
        stored_path = self._asset_manager.write_raw_file(
            workspace_path,
            asset_id,
            download.file_name,
            download.content,
        )
        try:
            analysis = self._analyzer.analyze(workspace_path / stored_path, attachment)
        except Exception as exc:
            analysis = AssetAnalysisResult(
                summary=f'Asset "{download.file_name}" was stored, but analysis failed.',
                tags=[attachment.kind.value],
                ingest_status="analysis_failed",
                ingest_error=str(exc),
                analysis_payload={
                "kind": attachment.kind.value,
                "file_name": download.file_name,
                "mime_type": download.mime_type or attachment.mime_type,
                },
            )
        derived_text_path = ""
        if analysis.derived_text:
            derived_text_path = self._asset_manager.write_derived_text(
                workspace_path,
                asset_id,
                analysis.derived_text,
            )
        analysis_path = self._asset_manager.write_analysis(
            workspace_path,
            asset_id,
            {
                **analysis.analysis_payload,
                "summary": analysis.summary,
                "tags": list(analysis.tags),
                "ingest_status": analysis.ingest_status,
                "ingest_error": analysis.ingest_error,
                "derived_text_path": derived_text_path,
            },
        )
        asset = CampaignAssetRecord(
            asset_id=asset_id,
            campaign_id=session.campaign_id or "",
            source_session_id=session.session_id,
            source_operator_id=session.operator_id,
            source_message_id=str(attachment.telegram_message_id or ""),
            source_attachment_id=attachment.attachment_id,
            kind=attachment.kind,
            telegram_file_id=attachment.telegram_file_id,
            telegram_file_unique_id=attachment.telegram_file_unique_id,
            stored_path=stored_path,
            derived_text_path=derived_text_path,
            analysis_path=analysis_path,
            original_file_name=download.file_name,
            mime_type=download.mime_type or attachment.mime_type,
            caption=attachment.caption,
            size_bytes=attachment.size_bytes,
            analysis_summary=analysis.summary,
            tags=analysis.tags,
            inferred_roles=analysis.inferred_roles,
            uncertainty_notes=analysis.uncertainty_notes,
            sendable=False,
            operator_labeled_sendable=False,
            ingest_status=analysis.ingest_status,
            ingest_error=analysis.ingest_error,
        )
        self._asset_manager.save_asset(workspace_path, asset)
        return asset

    def _merge_asset_refs_into_session(self, session: SessionRecord, asset_refs: list[str]) -> None:
        setup_state = get_campaign_setup_state(session)
        existing_refs = [
            str(asset_id).strip()
            for asset_id in setup_state.get("asset_refs", [])
            if str(asset_id).strip()
        ]
        for asset_id in asset_refs:
            if asset_id not in existing_refs:
                existing_refs.append(asset_id)
        setup_state["asset_refs"] = existing_refs
        save_campaign_setup_state(session, setup_state)

        snapshot_payload = session.workflow_state.get("workflow_snapshot", {})
        if isinstance(snapshot_payload, dict):
            data = snapshot_payload.get("data", {})
            if not isinstance(data, dict):
                data = {}
            data["asset_ref_count"] = len(existing_refs)
            data["recent_asset_refs"] = existing_refs[-5:]
            snapshot_payload["data"] = data
            session.workflow_state["workflow_snapshot"] = snapshot_payload

    def _apply_explicit_label_update(self, workspace_path: Path, message: str) -> str:
        asset_id, sendable = _parse_sendable_label_command(message)
        if not asset_id:
            return ""
        asset = self._asset_manager.update_sendable_label(workspace_path, asset_id, sendable=sendable)
        if asset is None:
            return f"I could not find asset `{asset_id}` to update its outbound eligibility."
        status_label = "sendable" if sendable else "not sendable"
        return f"Marked asset `{asset.asset_id}` as {status_label} for future outbound use."

    def _build_operator_message(
        self,
        attachments: list[TelegramAttachment],
        stored_count: int,
        *,
        uncertainty_notes: list[str],
    ) -> str:
        document_count = sum(1 for attachment in attachments if attachment.kind.value == "document")
        image_count = sum(1 for attachment in attachments if attachment.kind.value == "image")
        parts: list[str] = []
        if document_count:
            parts.append(f"{document_count} document")
        if image_count:
            parts.append(f"{image_count} image")
        if not parts:
            base_message = f"Stored {stored_count} campaign assets for context."
            return _append_uncertainty_note(base_message, uncertainty_notes)
        human_count = " and ".join(parts)
        suffix = "asset" if stored_count == 1 else "assets"
        base_message = f"Uploaded {human_count} {suffix} for campaign context."
        return _append_uncertainty_note(base_message, uncertainty_notes)


def _parse_sendable_label_command(message: str) -> tuple[str, bool]:
    normalized = " ".join(message.strip().split())
    if not normalized:
        return ("", False)

    patterns = (
        (r"^mark(?: asset)? (?P<asset_id>[a-z0-9-]+) sendable$", True),
        (r"^mark(?: asset)? (?P<asset_id>[a-z0-9-]+) not sendable$", False),
        (r"^mark(?: asset)? (?P<asset_id>[a-z0-9-]+) unsendable$", False),
    )
    lowered = normalized.lower()
    for pattern, sendable in patterns:
        match = re.match(pattern, lowered)
        if match:
            return (match.group("asset_id"), sendable)
    return ("", False)


def _append_uncertainty_note(base_message: str, uncertainty_notes: list[str]) -> str:
    if not uncertainty_notes:
        return base_message
    return base_message + " I noted some uncertainty about how these assets should be used beyond campaign context."
