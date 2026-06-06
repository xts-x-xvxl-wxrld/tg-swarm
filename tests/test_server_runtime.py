from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import importlib

import httpx

from telegram_app.engagement.listener import ManagedAccountEventListener
from telegram_app.engagement_brain.review_runner import ConversationReviewRunner
from telegram_app.live_execution.runner import LiveExecutionRunner
from telegram_app.monitoring import NullRuntimeEventLogger
from telegram_app.scheduling.runner import ScheduledWorkRunner
from telegram_app.transport import TelegramMessage, TelegramResponse


class FakeTelegramService:
    def __init__(self, response: TelegramResponse) -> None:
        self.response = response
        self.updates = []
        self.monitor = NullRuntimeEventLogger()

    def handle_update(self, update):  # noqa: ANN001
        self.updates.append(update)
        return self.response


class FakeBotClient:
    def __init__(self) -> None:
        self.deleted = False
        self.sent_messages: list[tuple[str, str, dict | None]] = []
        self.webhook_urls: list[str] = []

    async def send_message(self, chat_id: str, text: str, reply_markup=None) -> dict[str, object]:  # noqa: ANN001
        self.sent_messages.append((chat_id, text, reply_markup))
        return {
            "chat_id": chat_id,
            "message_id": len(self.sent_messages),
            "text": text,
        }

    async def get_me(self) -> dict[str, object]:
        return {"id": 1, "username": "tg_swarm_bot"}

    async def get_webhook_info(self) -> dict[str, object]:
        return {"url": "https://example.test/webhook"}

    async def set_webhook(self, webhook_url: str) -> dict[str, object]:
        self.webhook_urls.append(webhook_url)
        return {"ok": True, "url": webhook_url}

    async def delete_webhook(self) -> dict[str, object]:
        self.deleted = True
        return {"ok": True, "deleted": True}


def _load_server_module(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_SWARM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_RUNTIME_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    import server

    return importlib.reload(server)


async def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_webhook_route_returns_runtime_response_and_delivery_metadata(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)
    service = FakeTelegramService(
        TelegramResponse(
            chat_id="123",
            messages=[
                TelegramMessage(text="First response"),
                TelegramMessage(text="Second response"),
            ],
        )
    )
    bot_client = FakeBotClient()
    monkeypatch.setattr(server, "create_telegram_app_service", lambda: service)
    monkeypatch.setattr(server, "_create_telegram_bot_client", lambda: bot_client)
    app = server.build_app()

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/telegram/webhook",
            json={
                "message": {
                    "message_id": 7,
                    "chat": {"id": 123},
                    "from": {"id": 456},
                    "text": "hello there",
                }
            },
        )
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["chat_id"] == "123"
    assert payload["delivery"]["sent"] is True
    assert payload["delivery"]["count"] == 2
    assert [message["text"] for message in payload["messages"]] == ["First response", "Second response"]
    assert service.updates[0].chat_id == "123"
    assert service.updates[0].user_id == "456"
    assert service.updates[0].text == "hello there"
    assert bot_client.sent_messages == [
        ("123", "First response", None),
        ("123", "Second response", None),
    ]


def test_webhook_route_reports_delivery_disabled_without_bot_client(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)
    service = FakeTelegramService(TelegramResponse.single("123", "No bot token configured"))
    monkeypatch.setattr(server, "create_telegram_app_service", lambda: service)
    monkeypatch.setattr(server, "_create_telegram_bot_client", lambda: None)
    app = server.build_app()

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/telegram/webhook",
            json={
                "message": {
                    "message_id": 8,
                    "chat": {"id": 123},
                    "from": {"id": 456},
                    "text": "/start",
                }
            },
        )
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["delivery"] == {
        "sent": False,
        "reason": "telegram_bot_token_missing",
    }


def test_management_routes_require_configured_bot_client(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)
    service = FakeTelegramService(TelegramResponse.single("123", "unused"))
    monkeypatch.setattr(server, "create_telegram_app_service", lambda: service)
    monkeypatch.setattr(server, "_create_telegram_bot_client", lambda: None)
    app = server.build_app()

    response = asyncio.run(_request(app, "GET", "/telegram/me"))

    assert response.status_code == 500
    assert response.json()["detail"] == "TELEGRAM_BOT_TOKEN is not configured."


def test_management_routes_delegate_to_bot_client(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)
    service = FakeTelegramService(TelegramResponse.single("123", "unused"))
    bot_client = FakeBotClient()
    monkeypatch.setattr(server, "create_telegram_app_service", lambda: service)
    monkeypatch.setattr(server, "_create_telegram_bot_client", lambda: bot_client)
    app = server.build_app()

    me_response = asyncio.run(_request(app, "GET", "/telegram/me"))
    info_response = asyncio.run(_request(app, "GET", "/telegram/webhook/info"))
    set_response = asyncio.run(
        _request(
            app,
            "POST",
            "/telegram/webhook/set",
            json={"webhook_url": "https://example.test/tg"},
        )
    )
    delete_response = asyncio.run(_request(app, "POST", "/telegram/webhook/delete"))

    assert me_response.status_code == 200
    assert me_response.json()["username"] == "tg_swarm_bot"
    assert info_response.status_code == 200
    assert info_response.json()["url"] == "https://example.test/webhook"
    assert set_response.status_code == 200
    assert set_response.json()["url"] == "https://example.test/tg"
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert bot_client.webhook_urls == ["https://example.test/tg"]
    assert bot_client.deleted is True


def test_monitoring_routes_return_recent_runtime_history(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)
    app = server.build_app()

    webhook_response = asyncio.run(
        _request(
            app,
            "POST",
            "/telegram/webhook",
            json={
                "message": {
                    "message_id": 10,
                    "chat": {"id": 123},
                    "from": {"id": 456},
                    "text": "/start",
                }
            },
        )
    )
    status_response = asyncio.run(_request(app, "GET", "/ops/monitoring/status"))
    summary_response = asyncio.run(_request(app, "GET", "/ops/monitoring/summary"))
    alerts_response = asyncio.run(_request(app, "GET", "/ops/monitoring/alerts"))
    events_response = asyncio.run(_request(app, "GET", "/ops/monitoring/events?component=app_service"))
    metrics_response = asyncio.run(_request(app, "GET", "/metrics"))

    assert webhook_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json()["events_last_hour"] >= 1
    assert "failure_rate_last_hour" in status_response.json()
    assert summary_response.status_code == 200
    assert summary_response.json()["total_events"] >= 1
    assert alerts_response.status_code == 200
    assert alerts_response.json()["status"] in {"ok", "warn", "critical"}
    assert "thresholds" in alerts_response.json()
    assert events_response.status_code == 200
    assert events_response.json()["count"] >= 1
    assert any(event["component"] == "app_service" for event in events_response.json()["events"])
    assert metrics_response.status_code == 200
    assert "tg_swarm_runtime_events_window_total" in metrics_response.text
    assert "tg_swarm_runtime_health_status" in metrics_response.text


def test_monitoring_routes_require_api_key_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TG_SWARM_MONITORING_API_KEY", "secret-key")
    server = _load_server_module(monkeypatch, tmp_path)
    app = server.build_app()

    unauthorized_response = asyncio.run(_request(app, "GET", "/ops/monitoring/summary"))
    authorized_response = asyncio.run(
        _request(
            app,
            "GET",
            "/ops/monitoring/summary",
            headers={"x-monitoring-key": "secret-key"},
        )
    )

    assert unauthorized_response.status_code == 401
    assert authorized_response.status_code == 200


def test_monitoring_alerts_route_surfaces_threshold_breaches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TG_SWARM_MONITORING_MAX_DELIVERY_FAILURES", "0")
    monkeypatch.setenv("TG_SWARM_MONITORING_MAX_FAILED_EVENTS", "0")
    server = _load_server_module(monkeypatch, tmp_path)
    app = server.build_app()

    app.state.monitoring_store.record_event(
        component="telegram_transport",
        event_type="delivery_failed",
        payload={"error": "network"},
    )

    alerts_response = asyncio.run(_request(app, "GET", "/ops/monitoring/alerts"))

    payload = alerts_response.json()
    assert alerts_response.status_code == 200
    assert payload["status"] == "critical"
    assert any(alert["code"] == "delivery_failures_high" for alert in payload["alerts"])


def test_build_runtime_components_wires_control_plane_seams(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)

    components = server.build_runtime_components()

    assert components.session_manager is not None
    assert components.campaign_manager is not None
    assert components.compiled_intent_store is not None
    assert components.compiled_intent_applicator is not None
    assert components.orchestrator._compiled_intent_store is components.compiled_intent_store  # noqa: SLF001
    assert components.orchestrator._compiled_intent_applicator is components.compiled_intent_applicator  # noqa: SLF001
    assert components.orchestrator._continuous_ops_manager is components.continuous_ops_manager  # noqa: SLF001
    assert components.dependency_bundle.account_capability is not None
    assert components.dependency_bundle.community_capability is not None
    assert components.dependency_bundle.messaging_capability is not None


def test_worker_factories_build_runtime_runners(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)

    scheduled_runner = server.create_scheduled_work_runner()
    live_runner = server.create_live_execution_runner()
    review_runner = server.create_conversation_review_runner()

    assert isinstance(scheduled_runner, ScheduledWorkRunner)
    assert isinstance(live_runner, LiveExecutionRunner)
    assert isinstance(review_runner, ConversationReviewRunner)
    assert scheduled_runner.run_once(now=datetime.now(UTC)) == []
    assert live_runner.run_once() is None
    assert review_runner.run_once() is None


def test_managed_account_listener_factory_uses_available_dependency_bundle(monkeypatch, tmp_path) -> None:
    server = _load_server_module(monkeypatch, tmp_path)

    class FakeClientWrapper:
        def is_available(self) -> tuple[bool, str]:
            return True, ""

    fake_bundle = server.RuntimeDependencyBundle(
        account_registry=object(),
        client_wrapper=FakeClientWrapper(),
    )
    monkeypatch.setattr(server, "_build_runtime_dependency_bundle", lambda _state_dir: fake_bundle)

    listener = server.create_managed_account_event_listener(state_dir=tmp_path / "runtime-state")

    assert isinstance(listener, ManagedAccountEventListener)
    assert listener._registry is fake_bundle.account_registry  # noqa: SLF001
    assert listener._client_wrapper is fake_bundle.client_wrapper  # noqa: SLF001
