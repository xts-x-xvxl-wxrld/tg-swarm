"""Telegram-safe formatting helpers for Bot API outbound messages."""

from __future__ import annotations

from html import escape
import re

CODE_BLOCK_PATTERN = re.compile(r"```(?:[A-Za-z0-9_+-]+)?\r?\n(.*?)```", re.DOTALL)
INLINE_CODE_PATTERN = re.compile(r"`([^`\r\n]+)`")
BOLD_PATTERN = re.compile(r"\*\*([^\r\n*].*?)\*\*")
TELEGRAM_BOT_PARSE_MODE = "HTML"
TELEGRAM_MTPROTO_PARSE_MODE = "html"


def format_telegram_html(text: str) -> str:
    """Convert lightweight Markdown-style text into Telegram-safe HTML."""
    placeholders: list[str] = []

    def store_placeholder(rendered: str) -> str:
        placeholder = f"TG_TRANSPORT_PLACEHOLDER_{len(placeholders)}_TOKEN"
        placeholders.append(rendered)
        return placeholder

    def replace_code_block(match: re.Match[str]) -> str:
        code = match.group(1).strip("\r\n")
        return store_placeholder(f"<pre><code>{escape(code, quote=False)}</code></pre>")

    def replace_inline_code(match: re.Match[str]) -> str:
        return store_placeholder(f"<code>{escape(match.group(1), quote=False)}</code>")

    rendered = CODE_BLOCK_PATTERN.sub(replace_code_block, text)
    rendered = INLINE_CODE_PATTERN.sub(replace_inline_code, rendered)
    rendered = escape(rendered, quote=False)
    rendered = BOLD_PATTERN.sub(r"<b>\1</b>", rendered)

    for index, placeholder in enumerate(placeholders):
        rendered = rendered.replace(f"TG_TRANSPORT_PLACEHOLDER_{index}_TOKEN", placeholder)
    return rendered
