"""Study statistics for /stats and /streak (master plan section 7b).

Counted data:
  * minutes and AI-off minutes: **confirmed** paper entries only
  * active day: a confirmed paper entry OR a text diary entry with content
  * words, quizzes and commits come from their own tables

"Consistency" is active days / calendar days. Calendar days start at the
programme start date and stop at today; today is left out of the count while it
is still empty, so an unfinished day never lowers the percentage.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

from ..config import settings
from ..models.github import GitHubEvent
from ..models.study import DiaryEntry, PaperEntry, QuizSession, VocabCard
from . import paper
from .service import _tz, local_today

PERIODS = ("day", "week", "month", "year")
CATEGORY_KEYS = [k for k, _ in paper.CATEGORIES]


def program_start() -> dt.date:
    try:
        return dt.date.fromisoformat(settings.stats_start_date)
    except ValueError:
        return dt.date(2026, 11, 20)


@dataclass
class Days:
    """Everything known about each day, from confirmed data."""
    minutes: dict[dt.date, int] = field(default_factory=dict)
    categories: dict[dt.date, dict[str, int]] = field(default_factory=dict)
    ai_off: dict[dt.date, int] = field(default_factory=dict)
    active: set[dt.date] = field(default_factory=set)


def load_days(db) -> Days:
    d = Days()
    for e in db.query(PaperEntry).filter(PaperEntry.confirmed.is_(True)).all():
        cats = {k: int((e.minutes or {}).get(k) or 0) for k in CATEGORY_KEYS}
        d.categories[e.day] = cats
        d.minutes[e.day] = sum(cats.values())
        d.ai_off[e.day] = int(e.ai_off_minutes or 0)
        d.active.add(e.day)
    for e in db.query(DiaryEntry).all():
        if (e.learned or "").strip() or (e.recalled or "").strip():
            d.active.add(e.day)
    return d


# ── streaks ───────────────────────────────────────────────────────────

def current_streak(active: set[dt.date], today: dt.date) -> int:
    """Consecutive active days ending today, or yesterday while today is empty."""
    cursor = today if today in active else today - dt.timedelta(days=1)
    n = 0
    while cursor in active:
        n += 1
        cursor -= dt.timedelta(days=1)
    return n


def longest_streak(active: set[dt.date]) -> int:
    best = run = 0
    prev: dt.date | None = None
    for day in sorted(active):
        run = run + 1 if prev is not None and (day - prev).days == 1 else 1
        best = max(best, run)
        prev = day
    return best


# ── windows ───────────────────────────────────────────────────────────

def period_window(name: str, today: dt.date, start: dt.date) -> tuple[dt.date, dt.date]:
    """(first day, last day) of a period, never past today."""
    if name == "day":
        return today, today
    if name == "week":
        return today - dt.timedelta(days=today.weekday()), today
    if name == "month":
        return today.replace(day=1), today
    if name == "year":  # rolling years counted from the programme start
        k = max(0, (today - start).days) // 365
        ystart = start + dt.timedelta(days=365 * k)
        return ystart, min(today, ystart + dt.timedelta(days=364))
    raise ValueError(f"unknown period {name!r}")


def effective_range(ws: dt.date, we: dt.date, today: dt.date, start: dt.date, active: set[dt.date]):
    """The calendar days that count: from the programme start, not before it,
    and without today while today is still empty. Returns (first, last) or None."""
    first = max(ws, start)
    last = we - dt.timedelta(days=1) if (we == today and today not in active) else we
    return (first, last) if first <= last else None


def _days(first: dt.date, last: dt.date):
    for i in range((last - first).days + 1):
        yield first + dt.timedelta(days=i)


def _utc_bounds(first: dt.date, last: dt.date) -> tuple[dt.datetime, dt.datetime]:
    tz = _tz()
    lo = dt.datetime.combine(first, dt.time.min, tz).astimezone(dt.timezone.utc)
    hi = dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tz).astimezone(dt.timezone.utc)
    return lo, hi


# ── the statistics ────────────────────────────────────────────────────

@dataclass
class PeriodStats:
    name: str
    first: dt.date
    last: dt.date
    calendar_days: int
    total_minutes: int
    by_category: dict[str, int]
    ai_off_minutes: int
    active_days: int
    consistency: float | None            # 0..1, None without calendar days
    avg_per_day: int | None              # minutes per day that has minutes
    best_day: tuple[dt.date, int] | None
    prev_total: int
    change_pct: float | None
    zero_days: list[dt.date]
    steadiness: str | None               # "barqaror" | "aralash" | "notekis" | None
    words_added: int
    words_mastered: int
    quizzes: int
    quiz_avg: float | None
    commits: int
    streak_current: int
    streak_longest: int
    month1: dict[str, tuple[int, int]] | None = None  # target name -> (value, goal)


def compute(db, name: str, today: dt.date | None = None) -> PeriodStats:
    today = today or local_today()
    start = program_start()
    days = load_days(db)
    ws, we = period_window(name, today, start)
    rng = effective_range(ws, we, today, start, days.active)
    first, last = rng if rng else (ws, we)
    counted = list(_days(*rng)) if rng else []

    in_range = counted
    minutes = {d: days.minutes[d] for d in in_range if d in days.minutes}
    by_cat = {k: sum(days.categories[d][k] for d in in_range if d in days.categories) for k in CATEGORY_KEYS}
    total = sum(minutes.values())
    active_days = sum(1 for d in in_range if d in days.active)

    # Same elapsed length, right before the window.
    span = (we - ws).days + 1
    prev_first, prev_last = ws - dt.timedelta(days=span), ws - dt.timedelta(days=1)
    prev_total = sum(m for d, m in days.minutes.items() if prev_first <= d <= prev_last and d >= start)
    change = ((total - prev_total) / prev_total * 100) if prev_total > 0 else None

    values = [m for m in minutes.values() if m > 0]
    steadiness = None
    if len(values) >= 3 and statistics.mean(values) > 0:
        cv = statistics.pstdev(values) / statistics.mean(values)
        steadiness = "barqaror" if cv < 0.35 else "notekis" if cv >= 0.7 else "aralash"

    lo, hi = _utc_bounds(first, last) if rng else (None, None)
    words_added = quizzes = commits = 0
    quiz_scores: list[float] = []
    if rng:
        words_added = db.query(VocabCard).filter(VocabCard.created_at >= lo, VocabCard.created_at < hi).count()
        for q in db.query(QuizSession).filter(
            QuizSession.finished.is_(True), QuizSession.created_at >= lo, QuizSession.created_at < hi
        ):
            quizzes += 1
            if q.questions:
                quiz_scores.append(100.0 * (q.correct or 0) / len(q.questions))
        gh = db.query(GitHubEvent).filter(
            GitHubEvent.type == "Commit", GitHubEvent.created_at >= lo, GitHubEvent.created_at < hi
        )
        if settings.github_owner_login:
            gh = gh.filter(GitHubEvent.actor_login.ilike(settings.github_owner_login))
        commits = gh.count()

    mastered = db.query(VocabCard).filter(VocabCard.interval_days >= 21).count()

    best = max(minutes.items(), key=lambda kv: kv[1]) if minutes and max(minutes.values()) > 0 else None
    result = PeriodStats(
        name=name, first=first, last=last, calendar_days=len(counted),
        total_minutes=total, by_category=by_cat, ai_off_minutes=sum(days.ai_off.get(d, 0) for d in in_range),
        active_days=active_days,
        consistency=(active_days / len(counted)) if counted else None,
        avg_per_day=round(total / len(values)) if values else None,
        best_day=best, prev_total=prev_total, change_pct=change,
        zero_days=[d for d in in_range if d not in days.active],
        steadiness=steadiness, words_added=words_added, words_mastered=mastered,
        quizzes=quizzes, quiz_avg=(sum(quiz_scores) / len(quiz_scores)) if quiz_scores else None,
        commits=commits,
        streak_current=current_streak(days.active, today),
        streak_longest=longest_streak(days.active),
    )
    if name == "month" and 0 <= (today - start).days < 30:  # month 1 of the plan
        goal_end = start + dt.timedelta(days=29)
        m1 = [d for d in days.active if start <= d <= goal_end]
        m1_lo, m1_hi = _utc_bounds(start, goal_end)
        m1_words = db.query(VocabCard).filter(VocabCard.created_at >= m1_lo, VocabCard.created_at < m1_hi).count()
        result.month1 = {"kundalik kunlari": (len(m1), 25), "so'zlar": (m1_words, 200)}
    return result


# ── text ──────────────────────────────────────────────────────────────

_MONTHS = ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"]
_TITLE = {"day": "Bugun", "week": "Bu hafta", "month": "Bu oy", "year": "Yil"}


def fmt_min(n: int) -> str:
    return f"{n // 60} s {n % 60} d"


def _d(day: dt.date) -> str:
    return f"{day.day}-{_MONTHS[day.month - 1]}"


def stats_text(s: PeriodStats) -> str:
    head = f"📈 {_TITLE[s.name]}"
    if s.first != s.last:
        head += f" ({_d(s.first)} – {_d(s.last)})"
    if s.calendar_days == 0:
        if s.name == "day":
            return head + "\n\nBugun hali yozuv yo'q. Qog'oz kundalik rasmini yuboring."
        return head + "\n\nHali hisoblanadigan kun yo'q."
    lines = [head, ""]
    lines.append(
        f"⏱ Jami: {fmt_min(s.total_minutes)} · Faol kunlar: {s.active_days}/{s.calendar_days}"
        + (f" ({round(s.consistency * 100)}%)" if s.consistency is not None else "")
    )
    if s.total_minutes:
        lines.append("   " + " · ".join(f"{label} {fmt_min(s.by_category[k])}" for k, label in paper.CATEGORIES if s.by_category[k]))
        lines.append(f"🤖 AI'siz: {fmt_min(s.ai_off_minutes)}")
    lines.append(f"🔥 Ketma-ket: {s.streak_current} kun (eng uzun: {s.streak_longest})")
    if s.avg_per_day is not None:
        lines.append(f"📊 O'rtacha: {fmt_min(s.avg_per_day)} / kun" + (
            f" · eng yaxshi: {_d(s.best_day[0])} ({fmt_min(s.best_day[1])})" if s.best_day else ""))
    if s.change_pct is not None:
        arrow = "↗️" if s.change_pct > 0 else "↘️" if s.change_pct < 0 else "➡️"
        lines.append(f"{arrow} Oldingi davrga nisbatan: {s.change_pct:+.0f}%")
    if s.steadiness:
        lines.append(f"🧭 Barqarorlik: {s.steadiness}")
    if s.zero_days and s.name in ("week", "month"):
        shown = ", ".join(_d(d) for d in s.zero_days[:7]) + (" …" if len(s.zero_days) > 7 else "")
        lines.append(f"❗ Bo'sh kunlar: {shown}")
    lines.append(f"📚 So'zlar: +{s.words_added} qo'shildi · {s.words_mastered} mustahkam")
    if s.quizzes:
        lines.append(f"🧪 Imtihon: {s.quizzes} ta, o'rtacha {s.quiz_avg:.0f}%")
    if s.commits:
        lines.append(f"💻 Commit: {s.commits}")
    if s.month1:
        goals = " · ".join(f"{k} {v}/{g}" for k, (v, g) in s.month1.items())
        lines.append(f"🎯 1-oy maqsadi: {goals}")
    return "\n".join(lines)


def streak_text(db, today: dt.date | None = None) -> str:
    today = today or local_today()
    start = program_start()
    days = load_days(db)
    lines = [
        f"🔥 Hozirgi ketma-ketlik: {current_streak(days.active, today)} kun",
        f"🏆 Eng uzun: {longest_streak(days.active)} kun",
    ]
    rng = effective_range(start, today, today, start, days.active)
    if rng:
        counted = list(_days(*rng))
        active = sum(1 for d in counted if d in days.active)
        lines.append(f"📆 Barqarorlik: {active}/{len(counted)} kun ({round(100 * active / len(counted))}%)")
        zero = [d for d in counted if d not in days.active][-5:]
        if zero:
            lines.append("❗ So'nggi bo'sh kunlar: " + ", ".join(_d(d) for d in zero))
    return "\n".join(lines)


def has_data(db) -> bool:
    return bool(load_days(db).active)
