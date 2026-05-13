"""Small JSON file helpers for runtime state persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from typing import Any

logger = logging.getLogger(__name__)
_REPLACE_RETRY_DELAYS_SECONDS = (0.05, 0.1, 0.2)
_DIRECT_WRITE_RETRY_DELAYS_SECONDS = (0.05, 0.1, 0.2, 0.4)


def load_json_file(file_path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON object from disk, falling back to a caller-provided default."""
    path = Path(file_path)
    if not path.exists():
        return dict(default)

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in %s. Falling back to default payload.", path)
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def write_json_file(file_path: str | Path, payload: dict[str, Any]) -> None:
    """Persist a JSON object atomically so runtime state survives restarts."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized_payload = json.dumps(payload, indent=2, sort_keys=True)

    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as handle:
        handle.write(serialized_payload)
        handle.flush()
        temp_path = Path(handle.name)

    try:
        _replace_with_retries(temp_path, path)
    except PermissionError:
        logger.warning(
            "Atomic replace failed for %s. Falling back to direct overwrite after retries.",
            path,
        )
        _write_text_with_retries(path, serialized_payload)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temporary file %s after overwrite fallback.", temp_path)


def _replace_with_retries(temp_path: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for delay in (*_REPLACE_RETRY_DELAYS_SECONDS, None):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            if delay is None:
                break
            time.sleep(delay)
    if last_error is not None:
        raise last_error


def _write_text_with_retries(path: Path, serialized_payload: str) -> None:
    last_error: PermissionError | None = None
    for delay in (*_DIRECT_WRITE_RETRY_DELAYS_SECONDS, None):
        try:
            path.write_text(serialized_payload, encoding="utf-8")
            return
        except PermissionError as exc:
            last_error = exc
            if delay is None:
                break
            time.sleep(delay)
    if last_error is not None:
        raise last_error
