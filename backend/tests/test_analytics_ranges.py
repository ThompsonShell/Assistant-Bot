import datetime as dt

from app.analytics.ranges import compute_range

NOW = dt.datetime(2026, 3, 18, 12, 0, tzinfo=dt.timezone.utc)  # a Wednesday


def test_today():
    s, e = compute_range("today", "UTC", now=NOW)
    assert s == dt.datetime(2026, 3, 18, tzinfo=dt.timezone.utc)
    assert e == dt.datetime(2026, 3, 19, tzinfo=dt.timezone.utc)


def test_week_starts_monday():
    s, e = compute_range("week", "UTC", now=NOW)
    assert s.weekday() == 0
    assert s <= NOW < e
    assert e - s == dt.timedelta(days=7)


def test_month():
    s, e = compute_range("month", "UTC", now=NOW)
    assert (s.year, s.month, s.day) == (2026, 3, 1)
    assert (e.year, e.month, e.day) == (2026, 4, 1)


def test_year():
    s, e = compute_range("year", "UTC", now=NOW)
    assert s == dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert e == dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)


def test_timezone_shifts_day_boundary():
    # In Tashkent (UTC+5), 20:00 UTC is already the next day locally.
    now = dt.datetime(2026, 3, 18, 20, 0, tzinfo=dt.timezone.utc)
    s, _ = compute_range("today", "Asia/Tashkent", now=now)
    # Local day start 2026-03-19 00:00 +05:00 == 2026-03-18 19:00 UTC.
    assert s == dt.datetime(2026, 3, 18, 19, 0, tzinfo=dt.timezone.utc)
