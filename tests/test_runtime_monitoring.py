from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_app.monitoring import RuntimeMonitoringThresholds, SqliteRuntimeMonitoringStore, build_trace_context
from telegram_app.transport import TelegramUpdate


def test_sqlite_runtime_monitoring_store_records_queries_and_summarizes(tmp_path) -> None:
    store = SqliteRuntimeMonitoringStore(tmp_path / "monitoring" / "runtime_events.sqlite3")
    update = TelegramUpdate(chat_id="chat-1", user_id="operator-1", text="hello")
    trace_context = build_trace_context("trace-1", update=update)

    store.record_event(
        component="app_service",
        event_type="turn_received",
        trace_context=trace_context,
        update=update,
        payload={"route_hint": "workflow_turn"},
    )
    store.record_event(
        component="telegram_transport",
        event_type="delivery_failed",
        trace_context=trace_context,
        update=update,
        payload={"error": "network"},
    )

    recent_events = store.list_events(component="app_service", since=datetime.now(UTC) - timedelta(hours=1))
    summary = store.build_summary(hours=24)
    health = store.build_health_report(
        hours=24,
        thresholds=RuntimeMonitoringThresholds(
            max_failed_events=0,
            max_failure_rate=0.1,
            max_delivery_failures=0,
            max_turn_failures=1,
            max_event_age_seconds=3600,
        ),
    )
    metrics = store.render_prometheus_metrics(hours=24)

    assert len(recent_events) == 1
    assert recent_events[0]["event_type"] == "turn_received"
    assert summary["total_events"] == 2
    assert summary["failed_events"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["events_by_component"]["app_service"] == 1
    assert summary["events_by_component"]["telegram_transport"] == 1
    assert summary["events_by_type"]["delivery_failed"] == 1
    assert summary["telegram_delivery"]["delivery_failed"] == 1
    assert summary["app_turns"]["turn_received"] == 1
    assert health["status"] == "critical"
    assert any(alert["code"] == "delivery_failures_high" for alert in health["alerts"])
    assert any(alert["code"] == "failed_events_high" for alert in health["alerts"])
    assert "tg_swarm_runtime_failed_events_window_total" in metrics
    assert "tg_swarm_runtime_failure_rate" in metrics
    assert "tg_swarm_runtime_thresholds" in metrics
    assert "component=\"app_service\"" in metrics
