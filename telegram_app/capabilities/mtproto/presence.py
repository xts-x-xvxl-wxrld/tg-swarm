"""Presence helpers for human-like managed-account MTProto activity."""

from __future__ import annotations

import random
from asyncio import sleep
from time import sleep as blocking_sleep
from typing import Any

TYPING_CHARACTERS_PER_SECOND = 3.0
MIN_TYPING_SECONDS = 2.0
ONLINE_WINDOW_MIN_SECONDS = 15.0
ONLINE_WINDOW_MAX_SECONDS = 30.0
READ_CHARACTERS_PER_SECOND = 18.0
READ_JITTER_MIN_SECONDS = 1.0
READ_JITTER_MAX_SECONDS = 4.0
MIN_READ_SECONDS = 2.0
MAX_READ_SECONDS = 12.0
SEND_IMMEDIATE_RETRY_COUNT = 3
SEND_RETRY_BACKOFF_SECONDS = 120.0
SEND_FINAL_ATTEMPT_COUNT = 1
SEND_TOTAL_ATTEMPTS = 1 + SEND_IMMEDIATE_RETRY_COUNT + SEND_FINAL_ATTEMPT_COUNT

random_uniform = random.uniform


def typing_delay_seconds(text: str) -> float:
    """Return a short, bounded typing delay based on message size."""
    visible_text = " ".join(text.split())
    if not visible_text:
        return MIN_TYPING_SECONDS
    estimated_delay = len(visible_text) / TYPING_CHARACTERS_PER_SECOND
    return max(MIN_TYPING_SECONDS, estimated_delay)


def online_window_seconds() -> float:
    """Return the online-presence window before and after active work."""
    return random_uniform(ONLINE_WINDOW_MIN_SECONDS, ONLINE_WINDOW_MAX_SECONDS)


def read_delay_seconds(texts: list[str] | tuple[str, ...]) -> float:
    """Return a human-like delay before a read receipt is emitted."""
    visible_characters = sum(len(" ".join(text.split())) for text in texts if text.strip())
    base_delay = visible_characters / READ_CHARACTERS_PER_SECOND if visible_characters else 0.0
    jitter = random_uniform(READ_JITTER_MIN_SECONDS, READ_JITTER_MAX_SECONDS)
    return max(MIN_READ_SECONDS, min(MAX_READ_SECONDS, base_delay + jitter))


async def pause_for_seconds(seconds: float) -> None:
    """Async delay wrapper so tests can replace long presence waits safely."""
    await sleep(max(seconds, 0.0))


def block_for_seconds(seconds: float) -> None:
    """Blocking delay wrapper for synchronous retry backoff paths."""
    blocking_sleep(max(seconds, 0.0))


async def set_account_offline(client: Any) -> None:
    """Ask Telegram to show the account as offline when supported."""
    request_type = _load_update_status_request()
    if request_type is None or not callable(client):
        return
    await client(request_type(offline=True))


async def set_account_online(client: Any) -> None:
    """Ask Telegram to show the account as online while active work is happening."""
    request_type = _load_update_status_request()
    if request_type is None or not callable(client):
        return
    await client(request_type(offline=False))


async def show_typing_indicator(client: Any, chat_id: str, text: str) -> None:
    """Show a brief typing indicator before sending a text reply."""
    action = getattr(client, "action", None)
    if not callable(action):
        return
    async with action(chat_id, "typing"):
        await pause_for_seconds(typing_delay_seconds(text))


async def open_online_window(client: Any) -> None:
    """Show the managed account as online before an active human-like action."""
    await set_account_online(client)
    await pause_for_seconds(online_window_seconds())


async def close_online_window(client: Any) -> None:
    """Keep the account online briefly after work, then return it offline."""
    await pause_for_seconds(online_window_seconds())
    await set_account_offline(client)


async def simulate_read_delay(texts: list[str] | tuple[str, ...]) -> None:
    """Pause before issuing a read receipt so reads are not perfectly instant."""
    await pause_for_seconds(read_delay_seconds(texts))


def _load_update_status_request():
    try:
        from telethon.tl.functions.account import UpdateStatusRequest
    except ModuleNotFoundError:
        return None
    return UpdateStatusRequest
