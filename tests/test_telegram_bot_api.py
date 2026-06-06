from __future__ import annotations

import asyncio

from telegram_app.transport.formatting import format_telegram_html
from telegram_app.transport.telegram_bot_api import TelegramBotApiClient


def test_format_telegram_html_converts_common_markdown_lite_patterns() -> None:
    text = "Use `activate` and **review carefully**.\n\n```json\n{\"ok\": true}\n```"

    rendered = format_telegram_html(text)

    assert rendered == (
        "Use <code>activate</code> and <b>review carefully</b>.\n\n"
        "<pre><code>{\"ok\": true}</code></pre>"
    )


def test_format_telegram_html_escapes_literal_html_outside_formatting() -> None:
    rendered = format_telegram_html("2 < 3 & keep `x < y` literal")

    assert rendered == "2 &lt; 3 &amp; keep <code>x &lt; y</code> literal"


def test_send_message_uses_html_parse_mode(monkeypatch) -> None:
    client = TelegramBotApiClient("token")
    captured: dict[str, object] = {}

    async def fake_post(self, method: str, payload: dict[str, object], timeout_seconds=None):  # noqa: ANN001, ARG001
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(TelegramBotApiClient, "_post", fake_post)

    asyncio.run(client.send_message("123", "Run `activate` next."))

    assert captured["method"] == "sendMessage"
    assert captured["payload"] == {
        "chat_id": "123",
        "text": "Run <code>activate</code> next.",
        "parse_mode": "HTML",
    }
