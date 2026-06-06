"""Campaign asset manifest and workspace helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from telegram_app.models import CampaignAssetRecord
from telegram_app.transport import TelegramAttachment

ASSETS_ROOT = "assets"
RAW_DIR = "assets/raw"
DERIVED_DIR = "assets/derived"
ANALYSIS_DIR = "assets/analysis"
MANIFEST_PATH = "assets/manifest.json"
_MANIFEST_VERSION = 1


class CampaignAssetManager:
    """Persist and query campaign asset metadata under the campaign workspace."""

    def ensure_workspace(self, workspace_path: str | Path) -> None:
        """Ensure the campaign asset directories exist."""
        workspace = Path(workspace_path)
        for relative_path in (ASSETS_ROOT, RAW_DIR, DERIVED_DIR, ANALYSIS_DIR):
            (workspace / relative_path).mkdir(parents=True, exist_ok=True)

    def list_assets(self, workspace_path: str | Path) -> list[CampaignAssetRecord]:
        """Return all manifest assets, newest first."""
        payload = self._load_manifest_payload(workspace_path)
        raw_assets = payload.get("assets", [])
        if not isinstance(raw_assets, list):
            return []
        assets = [CampaignAssetRecord.from_dict(item) for item in raw_assets if isinstance(item, dict)]
        return sorted(assets, key=lambda asset: asset.created_at, reverse=True)

    def find_existing_asset(
        self,
        workspace_path: str | Path,
        attachment: TelegramAttachment,
    ) -> CampaignAssetRecord | None:
        """Return an already ingested asset for the same Telegram attachment when present."""
        for asset in self.list_assets(workspace_path):
            if (
                asset.source_message_id == str(attachment.telegram_message_id or "")
                and asset.source_attachment_id == attachment.attachment_id
            ):
                return asset
            if attachment.telegram_file_unique_id and asset.telegram_file_unique_id == attachment.telegram_file_unique_id:
                return asset
        return None

    def get_asset(self, workspace_path: str | Path, asset_id: str) -> CampaignAssetRecord | None:
        """Return one asset by identifier."""
        normalized_id = asset_id.strip()
        if not normalized_id:
            return None
        for asset in self.list_assets(workspace_path):
            if asset.asset_id == normalized_id:
                return asset
        return None

    def save_asset(self, workspace_path: str | Path, asset: CampaignAssetRecord) -> None:
        """Insert or update one asset in the manifest."""
        self.ensure_workspace(workspace_path)
        payload = self._load_manifest_payload(workspace_path)
        assets = payload.setdefault("assets", [])
        if not isinstance(assets, list):
            assets = []
            payload["assets"] = assets

        asset.touch()
        serialized_asset = asset.to_dict()
        for index, item in enumerate(assets):
            if isinstance(item, dict) and item.get("asset_id") == asset.asset_id:
                assets[index] = serialized_asset
                break
        else:
            assets.append(serialized_asset)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._write_manifest_payload(workspace_path, payload)

    def write_raw_file(
        self,
        workspace_path: str | Path,
        asset_id: str,
        file_name: str,
        content: bytes,
    ) -> str:
        """Persist the original inbound file and return its workspace-relative path."""
        safe_name = self._safe_file_name(file_name)
        relative_path = f"{RAW_DIR}/{asset_id}--{safe_name}"
        file_path = Path(workspace_path) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return relative_path

    def write_derived_text(
        self,
        workspace_path: str | Path,
        asset_id: str,
        text: str,
    ) -> str:
        """Persist extracted document text and return its relative path."""
        relative_path = f"{DERIVED_DIR}/{asset_id}.txt"
        file_path = Path(workspace_path) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")
        return relative_path

    def write_analysis(
        self,
        workspace_path: str | Path,
        asset_id: str,
        payload: dict[str, Any],
    ) -> str:
        """Persist one structured analysis sidecar and return its relative path."""
        relative_path = f"{ANALYSIS_DIR}/{asset_id}.json"
        file_path = Path(workspace_path) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return relative_path

    def update_sendable_label(
        self,
        workspace_path: str | Path,
        asset_id: str,
        *,
        sendable: bool,
    ) -> CampaignAssetRecord | None:
        """Persist an explicit operator label for outbound eligibility."""
        asset = self.get_asset(workspace_path, asset_id)
        if asset is None:
            return None
        asset.operator_labeled_sendable = sendable
        asset.sendable = sendable
        self.save_asset(workspace_path, asset)
        return asset

    def build_asset_id(self, attachment: TelegramAttachment) -> str:
        """Build a stable asset id for a normalized Telegram attachment."""
        message_id = str(attachment.telegram_message_id or "message")
        raw_value = f"{message_id}-{attachment.kind.value}-{attachment.attachment_id}"
        return self._slugify(raw_value)

    def build_prompt_asset_refs(
        self,
        workspace_path: str | Path,
        *,
        preferred_asset_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return compact prompt-facing asset refs."""
        assets = self.list_assets(workspace_path)
        if preferred_asset_ids:
            preferred_lookup = {asset_id for asset_id in preferred_asset_ids if asset_id}
            ranked_assets = [asset for asset in assets if asset.asset_id in preferred_lookup]
            ranked_assets.extend(asset for asset in assets if asset.asset_id not in preferred_lookup)
            assets = ranked_assets

        refs: list[dict[str, Any]] = []
        for asset in assets[:limit]:
            refs.append(
                {
                    "asset_id": asset.asset_id,
                    "kind": asset.kind.value,
                    "summary": asset.analysis_summary,
                    "tags": list(asset.tags[:5]),
                    "inferred_roles": list(asset.inferred_roles),
                    "uncertainty_notes": list(asset.uncertainty_notes[:2]),
                    "sendable": asset.sendable,
                }
            )
        return refs

    def _load_manifest_payload(self, workspace_path: str | Path) -> dict[str, Any]:
        self.ensure_workspace(workspace_path)
        manifest_path = Path(workspace_path) / MANIFEST_PATH
        if not manifest_path.exists():
            return {
                "version": _MANIFEST_VERSION,
                "assets": [],
                "updated_at": datetime.now(UTC).isoformat(),
            }
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("version", _MANIFEST_VERSION)
        payload.setdefault("assets", [])
        payload.setdefault("updated_at", datetime.now(UTC).isoformat())
        return payload

    def _write_manifest_payload(self, workspace_path: str | Path, payload: dict[str, Any]) -> None:
        manifest_path = Path(workspace_path) / MANIFEST_PATH
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _safe_file_name(self, file_name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip())
        return cleaned.strip("-.") or "attachment.bin"

    def _slugify(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
        return cleaned.strip("-") or "asset"
