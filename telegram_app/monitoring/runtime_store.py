"""SQLite-backed runtime monitoring store with query and summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.monitoring.runtime_events import RuntimeTraceContext
from telegram_app.monitoring.runtime_logger import build_runtime_event_record
from telegram_app.transport import TelegramUpdate

DEFAULT_SUMMARY_FAILURE_LIMIT = 10
MAX_EVENT_QUERY_LIMIT = 250
DEFAULT_RECENT_FAILURE_ALERT_LIMIT = 5


@dataclass(frozen=True, slots=True)
class RuntimeMonitoringThresholds:
    """Configurable alert thresholds for recent runtime health evaluation."""

    max_failed_events: int = 5
    max_failure_rate: float = 0.2
    max_delivery_failures: int = 2
    max_turn_failures: int = 1
    max_event_age_seconds: int = 900


class SqliteRuntimeMonitoringStore:
    """Persist runtime events into SQLite for durable querying and summaries."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def path(self) -> Path:
        """Expose the backing SQLite path for diagnostics and API reporting."""
        return self._file_path

    def record_event(
        self,
        *,
        component: str,
        event_type: str,
        trace_context: RuntimeTraceContext | None = None,
        session: SessionRecord | None = None,
        approval: ApprovalRecord | None = None,
        update: TelegramUpdate | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Insert one normalized runtime event into the durable store."""
        event = build_runtime_event_record(
            component=component,
            event_type=event_type,
            trace_context=trace_context,
            session=session,
            approval=approval,
            update=update,
            payload=payload,
        )
        trace_payload = _as_dict(event.get("trace"))
        session_payload = _as_dict(event.get("session"))
        approval_payload = _as_dict(event.get("approval"))
        update_payload = _as_dict(event.get("update"))

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO runtime_events (
                        event_id,
                        recorded_at,
                        component,
                        event_type,
                        trace_id,
                        chat_id,
                        user_id,
                        session_id,
                        campaign_id,
                        approval_id,
                        workflow_stage,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.get("event_id", "")),
                        str(event.get("recorded_at", "")),
                        str(event.get("component", "")),
                        str(event.get("event_type", "")),
                        str(trace_payload.get("trace_id", "")),
                        str(trace_payload.get("chat_id") or update_payload.get("chat_id") or ""),
                        str(trace_payload.get("user_id") or update_payload.get("user_id") or ""),
                        str(trace_payload.get("session_id") or session_payload.get("session_id") or ""),
                        str(session_payload.get("campaign_id", "") or ""),
                        str(approval_payload.get("approval_id", "") or ""),
                        str(trace_payload.get("workflow_stage") or session_payload.get("workflow_stage") or ""),
                        json.dumps(event, ensure_ascii=True, sort_keys=True, default=str),
                    ),
                )

    def list_events(
        self,
        *,
        component: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        chat_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        campaign_id: str | None = None,
        workflow_stage: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent runtime events matching one or more indexed filters."""
        bounded_limit = max(1, min(int(limit), MAX_EVENT_QUERY_LIMIT))
        where_clauses = ["1 = 1"]
        params: list[object] = []
        for column, value in (
            ("component", component),
            ("event_type", event_type),
            ("trace_id", trace_id),
            ("chat_id", chat_id),
            ("user_id", user_id),
            ("session_id", session_id),
            ("campaign_id", campaign_id),
            ("workflow_stage", workflow_stage),
        ):
            if value:
                where_clauses.append(f"{column} = ?")
                params.append(str(value).strip())
        if since is not None:
            where_clauses.append("recorded_at >= ?")
            params.append(_normalize_datetime(since).isoformat())

        query = f"""
            SELECT event_json
            FROM runtime_events
            WHERE {' AND '.join(where_clauses)}
            ORDER BY recorded_at DESC
            LIMIT ?
        """
        params.append(bounded_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(str(row["event_json"])) for row in rows]

    def build_summary(self, *, hours: int = 24) -> dict[str, Any]:
        """Return one compact operational summary over a recent time window."""
        window_hours = max(1, int(hours))
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        since_iso = since.isoformat()
        with self._connect() as connection:
            total_events = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_events WHERE recorded_at >= ?",
                    (since_iso,),
                ).fetchone()[0]
            )
            failed_events = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runtime_events
                    WHERE recorded_at >= ? AND event_type LIKE '%failed%'
                    """,
                    (since_iso,),
                ).fetchone()[0]
            )
            latest_event_at = connection.execute(
                "SELECT MAX(recorded_at) FROM runtime_events",
            ).fetchone()[0]
            unique_trace_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT trace_id)
                    FROM runtime_events
                    WHERE recorded_at >= ? AND trace_id != ''
                    """,
                    (since_iso,),
                ).fetchone()[0]
            )
            unique_session_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT session_id)
                    FROM runtime_events
                    WHERE recorded_at >= ? AND session_id != ''
                    """,
                    (since_iso,),
                ).fetchone()[0]
            )
            unique_chat_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT chat_id)
                    FROM runtime_events
                    WHERE recorded_at >= ? AND chat_id != ''
                    """,
                    (since_iso,),
                ).fetchone()[0]
            )
            unique_campaign_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT campaign_id)
                    FROM runtime_events
                    WHERE recorded_at >= ? AND campaign_id != ''
                    """,
                    (since_iso,),
                ).fetchone()[0]
            )
            events_by_component = _read_counts(
                connection,
                """
                SELECT component, COUNT(*) AS total
                FROM runtime_events
                WHERE recorded_at >= ?
                GROUP BY component
                ORDER BY total DESC, component ASC
                """,
                since_iso,
            )
            events_by_type = _read_counts(
                connection,
                """
                SELECT event_type, COUNT(*) AS total
                FROM runtime_events
                WHERE recorded_at >= ?
                GROUP BY event_type
                ORDER BY total DESC, event_type ASC
                """,
                since_iso,
            )
            stages = _read_counts(
                connection,
                """
                SELECT workflow_stage, COUNT(*) AS total
                FROM runtime_events
                WHERE recorded_at >= ? AND workflow_stage != ''
                GROUP BY workflow_stage
                ORDER BY total DESC, workflow_stage ASC
                """,
                since_iso,
            )
            telegram_delivery = _read_event_type_totals(
                connection,
                since_iso,
                event_types=("delivery_completed", "delivery_failed", "delivery_skipped"),
            )
            app_turns = _read_event_type_totals(
                connection,
                since_iso,
                event_types=("turn_received", "turn_failed", "response_prepared", "workflow_stage_changed"),
            )
            recent_failures = [
                json.loads(str(row["event_json"]))
                for row in connection.execute(
                    """
                    SELECT event_json
                    FROM runtime_events
                    WHERE recorded_at >= ? AND event_type LIKE '%failed%'
                    ORDER BY recorded_at DESC
                    LIMIT ?
                    """,
                    (since_iso, DEFAULT_SUMMARY_FAILURE_LIMIT),
                ).fetchall()
            ]

        latest_event_age_seconds = _seconds_since_iso(latest_event_at)
        failure_rate = (failed_events / total_events) if total_events else 0.0
        throughput = {
            "events_per_hour": round(total_events / max(window_hours, 1), 4),
            "events_per_minute": round(total_events / max(window_hours * 60, 1), 4),
        }
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "window_hours": window_hours,
            "since": since_iso,
            "total_events": total_events,
            "failed_events": failed_events,
            "failure_rate": round(failure_rate, 6),
            "latest_event_at": latest_event_at,
            "latest_event_age_seconds": latest_event_age_seconds,
            "unique_traces": unique_trace_count,
            "unique_sessions": unique_session_count,
            "unique_chats": unique_chat_count,
            "unique_campaigns": unique_campaign_count,
            "throughput": throughput,
            "events_by_component": events_by_component,
            "events_by_type": events_by_type,
            "workflow_stages": stages,
            "telegram_delivery": telegram_delivery,
            "app_turns": app_turns,
            "recent_failures": recent_failures,
        }

    def render_prometheus_metrics(
        self,
        *,
        hours: int = 24,
        thresholds: RuntimeMonitoringThresholds | None = None,
    ) -> str:
        """Render a small Prometheus-compatible metrics snapshot."""
        summary = self.build_summary(hours=hours)
        resolved_thresholds = thresholds or RuntimeMonitoringThresholds()
        health = self.build_health_report(hours=hours, thresholds=resolved_thresholds)
        lines = [
            "# HELP tg_swarm_runtime_events_window_total Runtime events recorded in the requested time window.",
            "# TYPE tg_swarm_runtime_events_window_total gauge",
            f"tg_swarm_runtime_events_window_total{{window_hours=\"{summary['window_hours']}\"}} {summary['total_events']}",
            "# HELP tg_swarm_runtime_failed_events_window_total Failed runtime events recorded in the requested time window.",
            "# TYPE tg_swarm_runtime_failed_events_window_total gauge",
            f"tg_swarm_runtime_failed_events_window_total{{window_hours=\"{summary['window_hours']}\"}} {summary['failed_events']}",
            "# HELP tg_swarm_runtime_failure_rate Recent failed-event ratio in the requested time window.",
            "# TYPE tg_swarm_runtime_failure_rate gauge",
            f"tg_swarm_runtime_failure_rate{{window_hours=\"{summary['window_hours']}\"}} {summary['failure_rate']}",
            "# HELP tg_swarm_runtime_latest_event_age_seconds Seconds since the most recent runtime event.",
            "# TYPE tg_swarm_runtime_latest_event_age_seconds gauge",
            f"tg_swarm_runtime_latest_event_age_seconds {summary['latest_event_age_seconds']}",
            "# HELP tg_swarm_runtime_unique_traces_window_total Distinct trace ids seen in the requested time window.",
            "# TYPE tg_swarm_runtime_unique_traces_window_total gauge",
            f"tg_swarm_runtime_unique_traces_window_total{{window_hours=\"{summary['window_hours']}\"}} {summary['unique_traces']}",
            "# HELP tg_swarm_runtime_unique_sessions_window_total Distinct session ids seen in the requested time window.",
            "# TYPE tg_swarm_runtime_unique_sessions_window_total gauge",
            f"tg_swarm_runtime_unique_sessions_window_total{{window_hours=\"{summary['window_hours']}\"}} {summary['unique_sessions']}",
            "# HELP tg_swarm_runtime_events_by_component Events grouped by runtime component in the requested time window.",
            "# TYPE tg_swarm_runtime_events_by_component gauge",
        ]
        for component, total in summary["events_by_component"].items():
            lines.append(
                f'tg_swarm_runtime_events_by_component{{window_hours="{summary["window_hours"]}",component="{_escape_metric_label(component)}"}} {total}'
            )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_events_by_type Events grouped by event type in the requested time window.",
                "# TYPE tg_swarm_runtime_events_by_type gauge",
            ]
        )
        for event_type, total in summary["events_by_type"].items():
            lines.append(
                f'tg_swarm_runtime_events_by_type{{window_hours="{summary["window_hours"]}",event_type="{_escape_metric_label(event_type)}"}} {total}'
            )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_telegram_delivery_events Recent telegram delivery event totals.",
                "# TYPE tg_swarm_runtime_telegram_delivery_events gauge",
            ]
        )
        for event_type, total in summary["telegram_delivery"].items():
            lines.append(
                f'tg_swarm_runtime_telegram_delivery_events{{window_hours="{summary["window_hours"]}",event_type="{_escape_metric_label(event_type)}"}} {total}'
            )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_app_turn_events Recent app turn lifecycle event totals.",
                "# TYPE tg_swarm_runtime_app_turn_events gauge",
            ]
        )
        for event_type, total in summary["app_turns"].items():
            lines.append(
                f'tg_swarm_runtime_app_turn_events{{window_hours="{summary["window_hours"]}",event_type="{_escape_metric_label(event_type)}"}} {total}'
            )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_alert_state Threshold-backed alert state where 1 means active.",
                "# TYPE tg_swarm_runtime_alert_state gauge",
            ]
        )
        for alert in health["alerts"]:
            lines.append(
                f'tg_swarm_runtime_alert_state{{alert_code="{_escape_metric_label(str(alert["code"]))}",severity="{_escape_metric_label(str(alert["severity"]))}"}} 1'
            )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_health_status Runtime health status encoded as ok=0, warn=1, critical=2.",
                "# TYPE tg_swarm_runtime_health_status gauge",
                f'tg_swarm_runtime_health_status{{status="{_escape_metric_label(str(health["status"]))}"}} {_status_rank(str(health["status"]))}',
            ]
        )
        lines.extend(
            [
                "# HELP tg_swarm_runtime_thresholds Configured alert thresholds for the monitoring surface.",
                "# TYPE tg_swarm_runtime_thresholds gauge",
                f'tg_swarm_runtime_thresholds{{threshold="max_failed_events"}} {resolved_thresholds.max_failed_events}',
                f'tg_swarm_runtime_thresholds{{threshold="max_failure_rate"}} {resolved_thresholds.max_failure_rate}',
                f'tg_swarm_runtime_thresholds{{threshold="max_delivery_failures"}} {resolved_thresholds.max_delivery_failures}',
                f'tg_swarm_runtime_thresholds{{threshold="max_turn_failures"}} {resolved_thresholds.max_turn_failures}',
                f'tg_swarm_runtime_thresholds{{threshold="max_event_age_seconds"}} {resolved_thresholds.max_event_age_seconds}',
            ]
        )
        return "\n".join(lines) + "\n"

    def build_health_report(
        self,
        *,
        hours: int = 24,
        thresholds: RuntimeMonitoringThresholds | None = None,
    ) -> dict[str, Any]:
        """Evaluate recent runtime health against configurable alert thresholds."""
        summary = self.build_summary(hours=hours)
        resolved_thresholds = thresholds or RuntimeMonitoringThresholds()
        alerts: list[dict[str, Any]] = []

        if summary["failed_events"] > resolved_thresholds.max_failed_events:
            alerts.append(
                _build_alert(
                    code="failed_events_high",
                    severity="critical",
                    observed=summary["failed_events"],
                    threshold=resolved_thresholds.max_failed_events,
                    message="Recent failed runtime events exceeded the configured threshold.",
                )
            )
        if summary["failure_rate"] > resolved_thresholds.max_failure_rate:
            alerts.append(
                _build_alert(
                    code="failure_rate_high",
                    severity="critical",
                    observed=summary["failure_rate"],
                    threshold=resolved_thresholds.max_failure_rate,
                    message="Recent failed-event ratio exceeded the configured threshold.",
                )
            )
        if summary["telegram_delivery"].get("delivery_failed", 0) > resolved_thresholds.max_delivery_failures:
            alerts.append(
                _build_alert(
                    code="delivery_failures_high",
                    severity="warn",
                    observed=summary["telegram_delivery"].get("delivery_failed", 0),
                    threshold=resolved_thresholds.max_delivery_failures,
                    message="Telegram delivery failures exceeded the configured threshold.",
                )
            )
        if summary["app_turns"].get("turn_failed", 0) > resolved_thresholds.max_turn_failures:
            alerts.append(
                _build_alert(
                    code="turn_failures_high",
                    severity="warn",
                    observed=summary["app_turns"].get("turn_failed", 0),
                    threshold=resolved_thresholds.max_turn_failures,
                    message="Operator turn failures exceeded the configured threshold.",
                )
            )
        if summary["latest_event_age_seconds"] > resolved_thresholds.max_event_age_seconds:
            alerts.append(
                _build_alert(
                    code="runtime_stale",
                    severity="warn",
                    observed=summary["latest_event_age_seconds"],
                    threshold=resolved_thresholds.max_event_age_seconds,
                    message="The runtime has not recorded a fresh event within the configured age threshold.",
                )
            )

        recent_failures = summary["recent_failures"][:DEFAULT_RECENT_FAILURE_ALERT_LIMIT]
        status = _derive_health_status(alerts)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "window_hours": summary["window_hours"],
            "summary": summary,
            "thresholds": {
                "max_failed_events": resolved_thresholds.max_failed_events,
                "max_failure_rate": resolved_thresholds.max_failure_rate,
                "max_delivery_failures": resolved_thresholds.max_delivery_failures,
                "max_turn_failures": resolved_thresholds.max_turn_failures,
                "max_event_age_seconds": resolved_thresholds.max_event_age_seconds,
            },
            "alerts": alerts,
            "recent_failures": recent_failures,
        }

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_events (
                        event_id TEXT PRIMARY KEY,
                        recorded_at TEXT NOT NULL,
                        component TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        trace_id TEXT NOT NULL,
                        chat_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        campaign_id TEXT NOT NULL,
                        approval_id TEXT NOT NULL,
                        workflow_stage TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                for index_sql in (
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_recorded_at ON runtime_events(recorded_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_component_type ON runtime_events(component, event_type)",
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_trace_id ON runtime_events(trace_id)",
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_session_id ON runtime_events(session_id)",
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_campaign_id ON runtime_events(campaign_id)",
                    "CREATE INDEX IF NOT EXISTS idx_runtime_events_workflow_stage ON runtime_events(workflow_stage)",
                ):
                    connection.execute(index_sql)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._file_path)
        connection.row_factory = sqlite3.Row
        return connection


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _seconds_since_iso(value: str | None) -> int:
    if not value:
        return 0
    normalized = value
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0
    return max(int((datetime.now(UTC) - _normalize_datetime(parsed)).total_seconds()), 0)


def _read_counts(connection: sqlite3.Connection, query: str, since_iso: str) -> dict[str, int]:
    rows = connection.execute(query, (since_iso,)).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row[0]).strip()
        if not key:
            continue
        counts[key] = int(row[1])
    return counts


def _read_event_type_totals(
    connection: sqlite3.Connection,
    since_iso: str,
    *,
    event_types: tuple[str, ...],
) -> dict[str, int]:
    counts = {event_type: 0 for event_type in event_types}
    if not event_types:
        return counts
    placeholders = ", ".join("?" for _ in event_types)
    rows = connection.execute(
        f"""
        SELECT event_type, COUNT(*) AS total
        FROM runtime_events
        WHERE recorded_at >= ? AND event_type IN ({placeholders})
        GROUP BY event_type
        """,
        (since_iso, *event_types),
    ).fetchall()
    for row in rows:
        event_type = str(row[0]).strip()
        if event_type in counts:
            counts[event_type] = int(row[1])
    return counts


def _build_alert(
    *,
    code: str,
    severity: str,
    observed: int | float,
    threshold: int | float,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "observed": observed,
        "threshold": threshold,
        "message": message,
    }


def _derive_health_status(alerts: list[dict[str, Any]]) -> str:
    if any(str(alert.get("severity", "")) == "critical" for alert in alerts):
        return "critical"
    if alerts:
        return "warn"
    return "ok"


def _status_rank(status: str) -> int:
    if status == "critical":
        return 2
    if status == "warn":
        return 1
    return 0


def _escape_metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
