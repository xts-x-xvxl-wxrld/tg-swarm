"""Time utility tools."""

from __future__ import annotations

from datetime import datetime


def get_current_time(timezone: str = "UTC") -> dict:
    """Get the current date and time in the specified timezone."""
    try:
        import pytz

        tz = pytz.timezone(timezone)
        current_time = datetime.now(tz)
        formatted_time = current_time.strftime("%A, %B %d, %Y - %I:%M:%S %p %Z")
        return {
            "ok": True,
            "timezone": timezone,
            "time": formatted_time,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
