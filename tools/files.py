"""File operation tools extracted from Agency Swarm BaseTool implementations."""

from __future__ import annotations

import mimetypes
import os
import shutil
from pathlib import Path


def _normalize_mnt_path(p: str) -> str:
    raw = (p or "").strip()
    if not raw:
        return raw
    if os.name != "nt":
        return raw
    if Path("/.dockerenv").is_file():
        return raw
    if raw.startswith("/mnt/") or raw == "/mnt":
        mnt = (Path("/app/mnt") if Path("/.dockerenv").is_file() else Path(__file__).parents[1] / "mnt").resolve()
        suffix = raw[len("/mnt/"):] if raw.startswith("/mnt/") else ""
        return str(mnt / suffix)
    return raw


def copy_file(source: str, destination: str) -> dict:
    """Copy a file from source to destination. Both paths must be absolute."""
    src = Path(_normalize_mnt_path(source))
    dst = Path(_normalize_mnt_path(destination))

    if not src.exists():
        return {"ok": False, "error": f"Source file not found: {src}"}
    if not src.is_file():
        return {"ok": False, "error": f"Source path is not a file: {src}"}

    if destination.endswith(("/", "\\")) or dst.is_dir():
        dst = dst / src.name

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {"ok": True, "message": f"Copied {src.name} to: {dst}"}


def read_file(path: str, offset: int | None = None, limit: int | None = None) -> dict:
    """Read a file from the local filesystem."""
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"ok": False, "error": f"File does not exist: {path}"}
        if not os.path.isfile(path):
            return {"ok": False, "error": f"Path is not a file: {path}"}

        mime_type, _ = mimetypes.guess_type(path)
        if mime_type and mime_type.startswith("image/"):
            return {
                "ok": True,
                "content": f"[IMAGE FILE: {path}]\nThis is an image file ({mime_type}).",
            }

        if path.endswith(".ipynb"):
            return {"ok": False, "error": "This is a Jupyter notebook file. Use a notebook-specific tool."}

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                lines = f.readlines()

        if not lines:
            return {"ok": True, "content": "", "warning": f"File exists but is empty: {path}"}

        start_line = (offset - 1) if offset else 0
        start_line = max(0, start_line)

        if limit:
            end_line = start_line + limit
            selected_lines = lines[start_line:end_line]
        else:
            selected_lines = lines[start_line: start_line + 2000]

        result_lines = []
        for i, line in enumerate(selected_lines, start=start_line + 1):
            if len(line) > 2000:
                line = line[:1997] + "...\n"
            result_lines.append(f"{i:>6}\t{line.rstrip()}\n")
        content = "".join(result_lines)

        total_lines = len(lines)
        lines_shown = len(selected_lines)
        if lines_shown < total_lines:
            if offset or limit:
                content += f"\n[Truncated: showing lines {start_line + 1}-{start_line + lines_shown} of {total_lines} total lines]"
            else:
                content += f"\n[Truncated: showing first {lines_shown} of {total_lines} total lines]"

        return {"ok": True, "content": content.rstrip()}

    except PermissionError:
        return {"ok": False, "error": f"Permission denied reading file: {path}"}
    except Exception as e:
        return {"ok": False, "error": f"Error reading file: {e}"}


def write_file(path: str, content: str) -> dict:
    """Write content to a file. Creates parent directories as needed."""
    try:
        if not os.path.isabs(path):
            return {"ok": False, "error": f"File path must be absolute: {path}"}

        file_exists = os.path.exists(path)
        if file_exists:
            if not os.path.isfile(path):
                return {"ok": False, "error": f"Path exists but is not a file: {path}"}
            operation = "overwritten"
        else:
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            operation = "created"

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        file_size = os.path.getsize(path)
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return {
            "ok": True,
            "message": f"Successfully {operation} file: {path}",
            "size_bytes": file_size,
            "lines": line_count,
        }

    except PermissionError:
        return {"ok": False, "error": f"Permission denied writing to file: {path}"}
    except Exception as e:
        return {"ok": False, "error": f"Error writing file: {e}"}


def list_directory(path: str, recursive: bool = False, max_depth: int = 3) -> dict:
    """List files and directories at the given absolute path."""
    try:
        if not os.path.isabs(path):
            return {"ok": False, "error": f"directory_path must be absolute: {path}"}
        if not os.path.exists(path):
            return {"ok": False, "error": f"Directory does not exist: {path}"}
        if not os.path.isdir(path):
            return {"ok": False, "error": f"Path is not a directory: {path}"}

        def list_dir_tree(dir_path: str, prefix: str = "", depth: int = 0) -> str:
            if depth > max_depth:
                return ""
            result = []
            try:
                entries = sorted(os.listdir(dir_path))
            except PermissionError:
                return f"{prefix}[Permission Denied]\n"

            ignore_patterns = {
                "__pycache__", ".git", ".venv", "venv", "node_modules",
                ".pytest_cache", ".mypy_cache", ".DS_Store",
            }
            filtered_entries = [
                e for e in entries
                if not e.startswith(".") and e not in ignore_patterns
            ]

            for i, entry in enumerate(filtered_entries):
                entry_path = os.path.join(dir_path, entry)
                is_last = i == len(filtered_entries) - 1
                connector = "└── " if is_last else "├── "
                new_prefix = prefix + ("    " if is_last else "│   ")

                if os.path.isdir(entry_path):
                    result.append(f"{prefix}{connector}{entry}/\n")
                    if recursive and depth < max_depth:
                        result.append(list_dir_tree(entry_path, new_prefix, depth + 1))
                else:
                    result.append(f"{prefix}{connector}{entry}\n")

            return "".join(result)

        output = f"{path}/\n" + list_dir_tree(path)
        if not output.strip():
            return {"ok": True, "content": f"Directory is empty: {path}"}
        return {"ok": True, "content": output.rstrip()}

    except Exception as e:
        return {"ok": False, "error": f"Error listing directory: {e}"}
