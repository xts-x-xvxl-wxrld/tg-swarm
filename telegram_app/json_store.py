"""Small JSON file helpers for runtime state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def load_json_file(file_path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON object from disk, falling back to a caller-provided default."""
    path = Path(file_path)
    if not path.exists():
        return dict(default)

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else dict(default)


def write_json_file(file_path: str | Path, payload: dict[str, Any]) -> None:
    """Persist a JSON object atomically so runtime state survives restarts."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        temp_path = Path(handle.name)

    temp_path.replace(path)
