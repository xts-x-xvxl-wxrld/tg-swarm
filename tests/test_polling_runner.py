import asyncio
import json

from telegram_app.polling_runner import JsonTelegramPollingCursorStore, TelegramPollingRunner
from telegram_app.transport import TelegramResponse


class _StopPolling(BaseException):
    pass


class FakeService:
    def __init__(self) -> None:
        self.updates = []
        self.monitor = _FakeMonitor()

    def handle_update(self, update):  # noqa: ANN001
        self.updates.append(update)
        return TelegramResponse.single(update.chat_id, "ack")


class _FakeMonitor:
    def record_event(self, **kwargs):  # noqa: ANN003, ANN001
        return None


class RetryDeleteWebhookBotClient:
    def __init__(self) -> None:
        self.delete_calls = 0
        self.update_calls = 0

    async def delete_webhook(self, drop_pending_updates: bool = False):  # noqa: ARG002
        self.delete_calls += 1
        if self.delete_calls == 1:
            raise RuntimeError("temporary delete failure")
        return {"ok": True}

    async def get_updates(self, offset=None, timeout=30, allowed_updates=None):  # noqa: ANN001, ARG002
        self.update_calls += 1
        raise _StopPolling()

    async def send_message(self, chat_id: str, text: str, reply_markup=None):  # noqa: ARG002
        return {"ok": True}


class RetryGetUpdatesBotClient:
    def __init__(self) -> None:
        self.delete_calls = 0
        self.update_calls = 0
        self.offsets: list[int | None] = []
        self.sent_messages: list[tuple[str, str]] = []

    async def delete_webhook(self, drop_pending_updates: bool = False):  # noqa: ARG002
        self.delete_calls += 1
        return {"ok": True}

    async def get_updates(self, offset=None, timeout=30, allowed_updates=None):  # noqa: ANN001, ARG002
        self.update_calls += 1
        self.offsets.append(offset)
        if self.update_calls == 1:
            raise RuntimeError("temporary polling failure")
        if self.update_calls == 2:
            return {
                "result": [
                    {
                        "update_id": 42,
                        "message": {
                            "message_id": 100,
                            "from": {"id": 519192084},
                            "chat": {"id": 519192084, "type": "private"},
                            "text": "hello",
                        },
                    }
                ]
            }
        raise _StopPolling()

    async def send_message(self, chat_id: str, text: str, reply_markup=None):  # noqa: ARG002
        self.sent_messages.append((chat_id, text))
        return {"ok": True}


class ReplayDuplicateUpdateBotClient:
    def __init__(self) -> None:
        self.delete_calls = 0
        self.offsets: list[int | None] = []
        self.sent_messages: list[tuple[str, str]] = []

    async def delete_webhook(self, drop_pending_updates: bool = False):  # noqa: ARG002
        self.delete_calls += 1
        return {"ok": True}

    async def get_updates(self, offset=None, timeout=30, allowed_updates=None):  # noqa: ANN001, ARG002
        self.offsets.append(offset)
        if len(self.offsets) == 1:
            return {
                "result": [
                    {
                        "update_id": 42,
                        "message": {
                            "message_id": 100,
                            "from": {"id": 519192084},
                            "chat": {"id": 519192084, "type": "private"},
                            "text": "hello again",
                        },
                    }
                ]
            }
        raise _StopPolling()

    async def send_message(self, chat_id: str, text: str, reply_markup=None):  # noqa: ARG002
        self.sent_messages.append((chat_id, text))
        return {"ok": True}


def test_polling_runner_retries_delete_webhook_before_polling() -> None:
    runner = TelegramPollingRunner(
        service=FakeService(),
        bot_client=RetryDeleteWebhookBotClient(),
        retry_delay_seconds=0,
    )

    try:
        asyncio.run(runner.run_forever())
    except _StopPolling:
        pass

    assert runner._bot_client.delete_calls == 2
    assert runner._bot_client.update_calls == 1


def test_polling_runner_retries_get_updates_and_continues_delivery(tmp_path) -> None:
    service = FakeService()
    bot_client = RetryGetUpdatesBotClient()
    cursor_store = JsonTelegramPollingCursorStore(tmp_path / "polling_cursor.json")
    runner = TelegramPollingRunner(
        service=service,
        bot_client=bot_client,
        retry_delay_seconds=0,
        cursor_store=cursor_store,
    )

    try:
        asyncio.run(runner.run_forever())
    except _StopPolling:
        pass

    assert bot_client.delete_calls == 1
    assert bot_client.update_calls == 3
    assert bot_client.offsets == [None, None, 43]
    assert len(service.updates) == 1
    assert bot_client.sent_messages == [("519192084", "ack")]
    assert runner._next_offset == 43
    persisted_payload = json.loads((tmp_path / "polling_cursor.json").read_text(encoding="utf-8"))
    assert persisted_payload["last_processed_update_id"] == 42


def test_polling_runner_restores_offset_from_persisted_update_id(tmp_path) -> None:
    cursor_store = JsonTelegramPollingCursorStore(tmp_path / "polling_cursor.json")
    cursor_store.save_last_processed_update_id(42)
    bot_client = RetryDeleteWebhookBotClient()
    runner = TelegramPollingRunner(
        service=FakeService(),
        bot_client=bot_client,
        retry_delay_seconds=0,
        cursor_store=cursor_store,
    )

    try:
        asyncio.run(runner.run_forever())
    except _StopPolling:
        pass

    assert runner._next_offset == 43
    assert bot_client.update_calls == 1


def test_polling_runner_skips_duplicate_update_from_persisted_cursor(tmp_path) -> None:
    service = FakeService()
    cursor_store = JsonTelegramPollingCursorStore(tmp_path / "polling_cursor.json")
    cursor_store.save_last_processed_update_id(42)
    bot_client = ReplayDuplicateUpdateBotClient()
    runner = TelegramPollingRunner(
        service=service,
        bot_client=bot_client,
        retry_delay_seconds=0,
        cursor_store=cursor_store,
    )

    try:
        asyncio.run(runner.run_forever())
    except _StopPolling:
        pass

    assert bot_client.delete_calls == 1
    assert bot_client.offsets == [43, 43]
    assert service.updates == []
    assert bot_client.sent_messages == []
    assert runner._next_offset == 43
