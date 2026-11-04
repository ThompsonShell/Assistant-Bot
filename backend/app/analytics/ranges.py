"""Compute UTC [start, end) windows for named ranges in a display timezone.

Events are stored in UTC; we interpret "today"/"this week" etc. in the user's
local timezone, then convert the boundaries back to UTC for querying.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

VALID_RANGES = (
    "today",
    "yesterday",
    "week",
    "last_week",
    "month",
    "last_month",
    "year",
)


def _tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - unknown tz falls back to UTC
        return ZoneInfo("UTC")


def compute_range(
    name: str, tz_name: str = "UTC", now: dt.datetime | None = None
) -> tuple[dt.datetime, dt.datetime]:
    """Return (start_utc, end_utc) for a named range."""
    tz = _tz(tz_name)
    now_local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if name == "today":
        start, end = day_start, day_start + dt.timedelta(days=1)
    elif name == "yesterday":
        start, end = day_start - dt.timedelta(days=1), day_start
    elif name == "week":
        start = day_start - dt.timedelta(days=day_start.weekday())
        end = start + dt.timedelta(days=7)
    elif name == "last_week":
        this_week = day_start - dt.timedelta(days=day_start.weekday())
        start, end = this_week - dt.timedelta(days=7), this_week
    elif name == "month":
        start = day_start.replace(day=1)
        end = _add_month(start)
    elif name == "last_month":
        this_month = day_start.replace(day=1)
        start, end = _prev_month(this_month), this_month
    elif name == "year":
        start = day_start.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    else:
        raise ValueError(f"Unknown range: {name!r}")

    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def _add_month(d: dt.datetime) -> dt.datetime:
    return d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)


def _prev_month(d: dt.datetime) -> dt.datetime:
    return d.replace(year=d.year - 1, month=12) if d.month == 1 else d.replace(month=d.month - 1)
