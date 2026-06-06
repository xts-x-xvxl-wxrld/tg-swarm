"""Sparse live-engagement notes that should survive campaign-memory re-renders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from telegram_app.json_store import load_json_file, write_json_file

EXECUTION_LOG_DESTINATION = "execution_log"
NEXT_ACTIONS_DESTINATION = "next_actions"
DEFAULT_NOTE_LIMIT = 100


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(slots=True)
class OperationalNote:
    """One durable operational note rendered into campaign memory."""

    note_id: str
    destination: str
    line: str
    category: str = ""
    dedupe_key: str = ""
    recorded_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "dedupe_key": self.dedupe_key,
            "destination": self.destination,
            "line": self.line,
            "note_id": self.note_id,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OperationalNote":
        payload = payload or {}
        return cls(
            note_id=str(payload.get("note_id", "")).strip(),
            destination=str(payload.get("destination", "")).strip(),
            line=str(payload.get("line", "")).strip(),
            category=str(payload.get("category", "")).strip(),
            dedupe_key=str(payload.get("dedupe_key", "")).strip(),
            recorded_at=_parse_datetime(str(payload.get("recorded_at", "")).strip()) or _utc_now(),
        )


class CampaignOperationalNotesStore:
    """Persist sparse operational notes alongside the campaign workspace."""

    def __init__(self, *, max_notes: int = DEFAULT_NOTE_LIMIT) -> None:
        self._lock = RLock()
        self._max_notes = max(max_notes, 1)

    def list_notes(self, workspace_path: str | Path) -> list[OperationalNote]:
        payload = load_json_file(
            self.path_for_workspace(workspace_path),
            default={"notes": [], "updated_at": ""},
        )
        raw_notes = payload.get("notes", [])
        if not isinstance(raw_notes, list):
            return []
        return [
            note
            for note in (
                OperationalNote.from_dict(item)
                for item in raw_notes
                if isinstance(item, dict)
            )
            if note.note_id and note.destination and note.line
        ]

    def append_note(
        self,
        workspace_path: str | Path,
        *,
        destination: str,
        line: str,
        category: str = "",
        dedupe_key: str = "",
        recorded_at: datetime | None = None,
    ) -> OperationalNote | None:
        normalized_destination = destination.strip()
        normalized_line = line.strip()
        if not normalized_destination or not normalized_line:
            return None

        workspace = Path(workspace_path)
        with self._lock:
            payload = load_json_file(
                self.path_for_workspace(workspace),
                default={"notes": [], "updated_at": ""},
            )
            raw_notes = payload.get("notes", [])
            notes = [
                OperationalNote.from_dict(item)
                for item in raw_notes
                if isinstance(raw_notes, list) and isinstance(item, dict)
            ]
            if dedupe_key.strip():
                for note in notes:
                    if note.destination == normalized_destination and note.dedupe_key == dedupe_key.strip():
                        return note

            note = OperationalNote(
                note_id=str(uuid4()),
                destination=normalized_destination,
                line=normalized_line,
                category=category.strip(),
                dedupe_key=dedupe_key.strip(),
                recorded_at=recorded_at or _utc_now(),
            )
            notes.append(note)
            notes = self._trim_notes(notes)
            write_json_file(
                self.path_for_workspace(workspace),
                {
                    "notes": [item.to_dict() for item in notes],
                    "updated_at": _utc_now().isoformat(),
                },
            )
            return note

    def path_for_workspace(self, workspace_path: str | Path) -> Path:
        return Path(workspace_path) / "artifacts" / "operational-notes.json"

    def _trim_notes(self, notes: list[OperationalNote]) -> list[OperationalNote]:
        trimmed: list[OperationalNote] = []
        for destination in {EXECUTION_LOG_DESTINATION, NEXT_ACTIONS_DESTINATION}:
            destination_notes = sorted(
                (note for note in notes if note.destination == destination),
                key=lambda item: item.recorded_at,
            )
            trimmed.extend(destination_notes[-self._max_notes :])
        return sorted(trimmed, key=lambda item: item.recorded_at)
