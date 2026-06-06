from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# Keep test runs isolated from a Telethon-oriented local .env.
os.environ["TELEGRAM_CAPABILITY_BACKEND"] = "stub"


if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=lambda *args, **kwargs: MagicMock())


if "telethon" not in sys.modules:
    class _StubTelegramClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.args = args
            self.kwargs = kwargs

    def _request_type(name: str):
        class _Request:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                self.args = args
                self.kwargs = kwargs

        _Request.__name__ = name
        return _Request

    telethon_module = types.ModuleType("telethon")
    telethon_module.TelegramClient = _StubTelegramClient

    tl_module = types.ModuleType("telethon.tl")
    functions_module = types.ModuleType("telethon.tl.functions")
    account_module = types.ModuleType("telethon.tl.functions.account")
    contacts_module = types.ModuleType("telethon.tl.functions.contacts")
    messages_module = types.ModuleType("telethon.tl.functions.messages")
    channels_module = types.ModuleType("telethon.tl.functions.channels")
    types_module = types.ModuleType("telethon.tl.types")
    events_module = types.ModuleType("telethon.events")

    account_module.UpdateStatusRequest = _request_type("UpdateStatusRequest")
    contacts_module.SearchRequest = _request_type("SearchRequest")
    messages_module.SearchGlobalRequest = _request_type("SearchGlobalRequest")
    channels_module.GetFullChannelRequest = _request_type("GetFullChannelRequest")
    channels_module.JoinChannelRequest = _request_type("JoinChannelRequest")
    types_module.InputMessagesFilterEmpty = _request_type("InputMessagesFilterEmpty")
    types_module.InputPeerEmpty = _request_type("InputPeerEmpty")
    events_module.NewMessage = _request_type("NewMessage")

    telethon_module.tl = tl_module
    telethon_module.events = events_module
    tl_module.functions = functions_module
    tl_module.types = types_module
    functions_module.account = account_module
    functions_module.contacts = contacts_module
    functions_module.messages = messages_module
    functions_module.channels = channels_module

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.events"] = events_module
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.functions"] = functions_module
    sys.modules["telethon.tl.functions.account"] = account_module
    sys.modules["telethon.tl.functions.contacts"] = contacts_module
    sys.modules["telethon.tl.functions.messages"] = messages_module
    sys.modules["telethon.tl.functions.channels"] = channels_module
    sys.modules["telethon.tl.types"] = types_module


@pytest.fixture(autouse=True)
def _fast_mtproto_presence_policy(monkeypatch):
    import telegram_app.capabilities.mtproto.presence as presence

    async def _no_pause(seconds: float) -> None:  # noqa: ARG001
        return None

    def _no_block(seconds: float) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(presence, "pause_for_seconds", _no_pause)
    monkeypatch.setattr(presence, "block_for_seconds", _no_block)
    monkeypatch.setattr(presence, "random_uniform", lambda minimum, maximum: (minimum + maximum) / 2)
