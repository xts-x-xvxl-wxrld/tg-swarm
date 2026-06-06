"""Best-effort campaign asset analysis helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from telegram_app.models import CampaignAssetKind, CampaignAssetRole
from telegram_app.transport import TelegramAttachment

_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
_COMMON_STOPWORDS = {
    "and",
    "asset",
    "campaign",
    "document",
    "file",
    "for",
    "from",
    "image",
    "jpeg",
    "jpg",
    "png",
    "telegram",
    "the",
    "this",
    "upload",
    "with",
}
_OUTBOUND_SIGNAL_PATTERNS = (
    re.compile(r"\b(send|share|post|publish|outbound)\b", re.IGNORECASE),
    re.compile(r"\b(ad|banner|brochure|creative|flyer|hero|poster|promo)\b", re.IGNORECASE),
)
_QUALIFICATION_SIGNAL_PATTERNS = (
    re.compile(r"\bfaq\b", re.IGNORECASE),
    re.compile(r"\b(icp|ideal customer profile)\b", re.IGNORECASE),
    re.compile(r"\b(eligibility|fit|qualified|qualification|requirements?)\b", re.IGNORECASE),
    re.compile(r"\bwho (?:it|this) is for\b", re.IGNORECASE),
)
_CONVERSION_SIGNAL_PATTERNS = (
    re.compile(r"\b(book|booking|call|contact|conversion|demo|dm|handoff|landing page)\b", re.IGNORECASE),
    re.compile(r"\b(apply|checkout|onboard|schedule|sign ?up|subscribe)\b", re.IGNORECASE),
)
_TRUST_SIGNAL_PATTERNS = (
    re.compile(r"\b(case study|customer story|proof|results?|review|testimonial|trust)\b", re.IGNORECASE),
    re.compile(r"\b(screenshot|success story|traction)\b", re.IGNORECASE),
)


@dataclass(slots=True)
class AssetAnalysisResult:
    """Structured result of one best-effort asset analysis pass."""

    summary: str
    tags: list[str] = field(default_factory=list)
    inferred_roles: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)
    ingest_status: str = "analyzed"
    ingest_error: str = ""
    derived_text: str = ""
    analysis_payload: dict[str, Any] = field(default_factory=dict)


class CampaignAssetAnalyzer:
    """Produce compact reusable summaries for stored campaign assets."""

    def analyze(
        self,
        stored_file_path: str | Path,
        attachment: TelegramAttachment,
    ) -> AssetAnalysisResult:
        """Analyze one stored asset by kind."""
        if attachment.kind is CampaignAssetKind.IMAGE:
            return self._analyze_image(stored_file_path, attachment)
        return self._analyze_document(stored_file_path, attachment)

    def _analyze_document(
        self,
        stored_file_path: str | Path,
        attachment: TelegramAttachment,
    ) -> AssetAnalysisResult:
        file_path = Path(stored_file_path)
        extracted_text, extraction_error = self._extract_document_text(file_path, attachment)
        display_name = attachment.file_name or file_path.name
        tags = self._document_tags(attachment)
        payload: dict[str, Any] = {
            "kind": attachment.kind.value,
            "file_name": display_name,
            "mime_type": attachment.mime_type,
            "caption": attachment.caption,
        }
        inferred_roles = _infer_asset_roles(
            attachment=attachment,
            file_name=display_name,
            extracted_text=extracted_text,
        )
        uncertainty_notes = _build_uncertainty_notes(
            attachment=attachment,
            inferred_roles=inferred_roles,
            extracted_text=extracted_text,
        )

        if not extracted_text:
            summary = f'Document "{display_name}" was stored, but text extraction was unavailable.'
            payload["extraction_available"] = False
            payload["inferred_roles"] = list(inferred_roles)
            payload["uncertainty_notes"] = list(uncertainty_notes)
            return AssetAnalysisResult(
                summary=summary,
                tags=tags,
                inferred_roles=inferred_roles,
                uncertainty_notes=uncertainty_notes,
                ingest_status="analysis_failed" if extraction_error else "stored",
                ingest_error=extraction_error,
                analysis_payload=payload,
            )

        snippet = _normalize_excerpt(extracted_text, limit=240)
        summary_parts = [f'Document "{display_name}" was stored.']
        if attachment.caption:
            summary_parts.append(f"Caption: {_normalize_excerpt(attachment.caption, limit=120)}.")
        summary_parts.append(f"Summary snippet: {snippet}")
        payload.update(
            {
                "extraction_available": True,
                "inferred_roles": list(inferred_roles),
                "uncertainty_notes": list(uncertainty_notes),
                "text_excerpt": snippet,
                "text_char_count": len(extracted_text),
            }
        )
        return AssetAnalysisResult(
            summary=" ".join(summary_parts).strip(),
            tags=tags,
            inferred_roles=inferred_roles,
            uncertainty_notes=uncertainty_notes,
            ingest_status="analyzed",
            derived_text=extracted_text,
            analysis_payload=payload,
        )

    def _analyze_image(
        self,
        stored_file_path: str | Path,
        attachment: TelegramAttachment,
    ) -> AssetAnalysisResult:
        display_name = attachment.file_name or Path(stored_file_path).name
        dimensions = ""
        if attachment.width and attachment.height:
            dimensions = f"{attachment.width}x{attachment.height}"
        orientation = _image_orientation(attachment.width, attachment.height)
        parts = [f'Image "{display_name}" was stored.']
        if dimensions:
            parts.append(f"Dimensions: {dimensions}.")
        if attachment.caption:
            parts.append(f"Caption: {_normalize_excerpt(attachment.caption, limit=160)}.")
        else:
            parts.append("No caption was provided.")
        tags = self._image_tags(attachment, orientation)
        inferred_roles = _infer_asset_roles(
            attachment=attachment,
            file_name=display_name,
            extracted_text="",
        )
        uncertainty_notes = _build_uncertainty_notes(
            attachment=attachment,
            inferred_roles=inferred_roles,
            extracted_text="",
        )
        return AssetAnalysisResult(
            summary=" ".join(parts).strip(),
            tags=tags,
            inferred_roles=inferred_roles,
            uncertainty_notes=uncertainty_notes,
            ingest_status="analyzed",
            analysis_payload={
                "kind": attachment.kind.value,
                "file_name": display_name,
                "mime_type": attachment.mime_type,
                "caption": attachment.caption,
                "width": attachment.width,
                "height": attachment.height,
                "orientation": orientation,
                "inferred_roles": list(inferred_roles),
                "uncertainty_notes": list(uncertainty_notes),
            },
        )

    def _extract_document_text(
        self,
        file_path: Path,
        attachment: TelegramAttachment,
    ) -> tuple[str, str]:
        suffix = file_path.suffix.lower()
        mime_type = attachment.mime_type.lower().strip()
        if suffix == ".docx":
            return self._extract_docx_text(file_path)
        if suffix in _TEXT_EXTENSIONS or mime_type.startswith("text/"):
            try:
                return (file_path.read_text(encoding="utf-8", errors="ignore").strip(), "")
            except OSError as exc:
                return ("", f"Could not read document text: {exc}")
        if suffix == ".pdf" or mime_type == "application/pdf":
            return ("", "PDF extraction is not available in the current runtime.")
        return ("", "Text extraction is not supported for this document type yet.")

    def _extract_docx_text(self, file_path: Path) -> tuple[str, str]:
        try:
            with ZipFile(file_path) as archive:
                xml_bytes = archive.read("word/document.xml")
        except (BadZipFile, KeyError, OSError) as exc:
            return ("", f"Could not read DOCX contents: {exc}")

        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            return ("", f"Could not parse DOCX XML: {exc}")

        text_runs = [node.text or "" for node in root.iter() if node.tag.endswith("}t") and (node.text or "").strip()]
        return ("\n".join(text_runs).strip(), "")

    def _document_tags(self, attachment: TelegramAttachment) -> list[str]:
        tags = ["document"]
        suffix = Path(attachment.file_name).suffix.lower().lstrip(".")
        if suffix:
            tags.append(suffix)
        tags.extend(_keyword_tags(attachment.caption, attachment.file_name))
        return _dedupe(tags)

    def _image_tags(self, attachment: TelegramAttachment, orientation: str) -> list[str]:
        tags = ["image"]
        suffix = Path(attachment.file_name).suffix.lower().lstrip(".")
        if suffix:
            tags.append(suffix)
        if orientation != "unknown":
            tags.append(orientation)
        tags.extend(_keyword_tags(attachment.caption, attachment.file_name))
        return _dedupe(tags)


def _normalize_excerpt(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _keyword_tags(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in re.split(r"[^a-zA-Z0-9]+", value.lower()):
            cleaned = token.strip()
            if len(cleaned) < 3 or cleaned in _COMMON_STOPWORDS:
                continue
            if cleaned not in tokens:
                tokens.append(cleaned)
            if len(tokens) >= 5:
                return tokens
    return tokens


def _image_orientation(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "unknown"
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _infer_asset_roles(
    *,
    attachment: TelegramAttachment,
    file_name: str,
    extracted_text: str,
) -> list[str]:
    combined_text = " ".join(
        value
        for value in (
            file_name,
            attachment.caption,
            extracted_text[:4000],
        )
        if value
    )
    roles = [CampaignAssetRole.CAMPAIGN_CONTEXT.value]

    if _matches_any_pattern(combined_text, _OUTBOUND_SIGNAL_PATTERNS):
        roles.append(CampaignAssetRole.OUTBOUND_MEDIA.value)
    if _matches_any_pattern(combined_text, _QUALIFICATION_SIGNAL_PATTERNS):
        roles.append(CampaignAssetRole.QUALIFICATION_MATERIAL.value)
    if _matches_any_pattern(combined_text, _CONVERSION_SIGNAL_PATTERNS):
        roles.append(CampaignAssetRole.CONVERSION_SUPPORT.value)
    if _matches_any_pattern(combined_text, _TRUST_SIGNAL_PATTERNS):
        roles.append(CampaignAssetRole.PROOF_OR_TRUST_SIGNAL.value)

    return _dedupe(roles)


def _build_uncertainty_notes(
    *,
    attachment: TelegramAttachment,
    inferred_roles: list[str],
    extracted_text: str,
) -> list[str]:
    notes: list[str] = []
    if inferred_roles == [CampaignAssetRole.CAMPAIGN_CONTEXT.value]:
        notes.append("Use beyond campaign context is still uncertain.")

    if attachment.kind is CampaignAssetKind.DOCUMENT and not extracted_text:
        notes.append("Role inference is limited because document text was not available.")

    if attachment.kind is CampaignAssetKind.IMAGE and not attachment.caption:
        notes.append("Role inference is limited because the image arrived without a caption.")

    return notes


def _matches_any_pattern(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) for pattern in patterns)
