import datetime as dt

import pytest

from app.bot import views
from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.jobs import telegram_bot as tb
from app.models.github import GitHubEvent
from app.models.study import DiaryEntry, PaperEntry, QuizSession, VocabCard
from app.study import stats
from app.study import service as study

START = dt.date(2026, 11, 20)
FRI27 = dt.date(2026, 11, 27)          # "today" in the fixed scenario


def day(n):                            # 2026-11-20 + n days
    return START + dt.timedelta(days=n)


@pytest.fixture
def db():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)()


@pytest.fixture(autouse=True)
def fixed_start(monkeypatch):
    monkeypatch.setattr(settings, "stats_start_date", "2026-11-20")
    monkeypatch.setattr(settings, "display_timezone", "UTC")
    monkeypatch.setattr(settings, "github_owner_login", None)


def paper(db, d, confirmed=True, ai_off=0, **minutes):
    m = {k: 0 for k in stats.CATEGORY_KEYS} | minutes
    db.add(PaperEntry(day=d, confirmed=confirmed, minutes=m, ai_off_minutes=ai_off, parsed={}, photo_paths=[]))
    db.commit()


@pytest.fixture
def week(db):
    """Fri 20 .. Thu 26 Nov, today = Fri 27 (still empty)."""
    paper(db, day(0), python=60, english=30, ai_off=60)                       # Fri 20
    paper(db, day(1), python=120, english=30)                                 # Sat 21
    db.add(DiaryEntry(day=day(2), learned="text only", recalled=""))          # Sun 22: text diary
    paper(db, day(3), python=90, english=45, algo=30, ai_off=120)             # Mon 23
    paper(db, day(5), python=100)                                             # Wed 25
    paper(db, day(6), confirmed=False, python=500)                            # Thu 26: NOT confirmed
    db.commit()
    return db


# ── streaks ───────────────────────────────────────────────────────────

def test_streak_functions():
    a = {day(0), day(1), day(2), day(4), day(5)}
    assert stats.longest_streak(a) == 3 and stats.longest_streak(set()) == 0
    assert stats.current_streak(a, day(5)) == 2
    assert stats.current_streak(a, day(6)) == 2          # today still empty: yesterday's streak survives
    assert stats.current_streak(a, day(7)) == 0          # a whole day missed
    assert stats.current_streak(set(), day(1)) == 0


def test_period_windows():
    assert stats.period_window("day", FRI27, START) == (FRI27, FRI27)
    assert stats.period_window("week", FRI27, START) == (dt.date(2026, 11, 23), FRI27)
    assert stats.period_window("month", FRI27, START) == (dt.date(2026, 11, 1), FRI27)
    assert stats.period_window("year", FRI27, START) == (START, FRI27)
    # Rolling years from the start date, not calendar years.
    later = dt.date(2027, 12, 1)
    assert stats.period_window("year", later, START) == (dt.date(2027, 11, 20), later)
    assert stats.period_window("year", dt.date(2027, 11, 19), START) == (START, dt.date(2027, 11, 19))
    with pytest.raises(ValueError):
        stats.period_window("decade", FRI27, START)


# ── numbers ───────────────────────────────────────────────────────────

def test_week_counts_only_confirmed_entries(week):
    s = stats.compute(week, "week", FRI27)
    assert (s.first, s.last) == (dt.date(2026, 11, 23), dt.date(2026, 11, 26))   # empty today not counted
    assert s.calendar_days == 4 and s.active_days == 2
    assert s.consistency == 0.5
    assert s.total_minutes == 165 + 100                  # the unconfirmed 500 is ignored
    assert s.by_category["python"] == 190 and s.by_category["english"] == 45 and s.by_category["algo"] == 30
    assert s.ai_off_minutes == 120
    assert s.best_day == (day(3), 165)
    assert abs(s.avg_per_day - 132.5) <= 0.5
    assert s.zero_days == [day(4), day(6)]               # Tue 24 and Thu 26 (unconfirmed = empty)
    assert s.steadiness is None                          # fewer than 3 days with minutes


def test_change_against_the_previous_period(week):
    s = stats.compute(week, "week", FRI27)
    assert s.prev_total == 90 + 150                      # 20, 21 (the days before the week, from the start)
    assert round(s.change_pct, 1) == round((265 - 240) / 240 * 100, 1)

    first = stats.compute(week, "day", day(0))           # nothing before the first day
    assert first.change_pct is None


def test_month_year_and_streaks(week):
    m = stats.compute(week, "month", FRI27)
    assert (m.first, m.last) == (START, dt.date(2026, 11, 26))      # month before the start doesn't count
    assert m.calendar_days == 7 and m.active_days == 5 and round(m.consistency, 2) == 0.71
    assert m.total_minutes == 90 + 150 + 165 + 100
    assert m.streak_current == 0 and m.streak_longest == 4          # Thu 26 is empty, so it is broken
    assert stats.compute(week, "year", FRI27).total_minutes == m.total_minutes


def test_today_counts_once_it_has_an_entry(week):
    paper(week, FRI27, python=45)
    s = stats.compute(week, "week", FRI27)
    assert s.last == FRI27 and s.calendar_days == 5 and s.active_days == 3
    assert s.streak_current == 1 and s.total_minutes == 265 + 45


def test_confirming_an_entry_makes_it_count(week):
    week.query(PaperEntry).filter(PaperEntry.confirmed.is_(False)).one().confirmed = True
    week.commit()
    s = stats.compute(week, "week", FRI27)
    assert s.total_minutes == 265 + 500 and s.active_days == 3


def test_before_the_start_nothing_is_counted(db):
    s = stats.compute(db, "week", dt.date(2026, 11, 19))
    assert s.calendar_days == 0 and s.consistency is None
    assert "Hali hisoblanadigan kun yo'q" in stats.stats_text(s)


def test_steadiness_label(db):
    for i, m in enumerate([100, 105, 110, 95]):
        paper(db, day(i), python=m)
    assert stats.compute(db, "month", day(4)).steadiness == "barqaror"
    db2 = make_sessionmaker(_engine())()
    for i, m in enumerate([10, 300, 20, 400]):
        paper(db2, day(i), python=m)
    assert stats.compute(db2, "month", day(4)).steadiness == "notekis"


def _engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_words_quizzes_and_commits_in_the_period(week, monkeypatch):
    def at(d):
        return dt.datetime.combine(d, dt.time(12, 0), dt.timezone.utc)

    week.add_all([
        VocabCard(word="in1", meaning="x", due_date=day(3), created_at=at(day(3))),
        VocabCard(word="in2", meaning="x", due_date=day(4), created_at=at(day(4)), interval_days=30),
        VocabCard(word="before", meaning="x", due_date=day(0), created_at=at(day(0))),
        QuizSession(questions=[{}, {}, {}, {}], correct=3.0, finished=True, created_at=at(day(4))),
        QuizSession(questions=[{}, {}], correct=2.0, finished=True, created_at=at(day(5))),
        QuizSession(questions=[{}], correct=0.0, finished=False, created_at=at(day(5))),    # unfinished
        GitHubEvent(gh_id="c1", repo_full_name="o/r", type="Commit", actor_login="me", actor_type="human",
                    title="t", created_at=at(day(4)), ingested_at=at(day(4))),
        GitHubEvent(gh_id="c2", repo_full_name="o/r", type="Commit", actor_login="other", actor_type="human",
                    title="t", created_at=at(day(4)), ingested_at=at(day(4))),
        GitHubEvent(gh_id="p1", repo_full_name="o/r", type="PullRequestEvent", actor_login="me",
                    actor_type="human", title="t", created_at=at(day(4)), ingested_at=at(day(4))),
    ])
    week.commit()
    s = stats.compute(week, "week", FRI27)
    assert s.words_added == 2 and s.words_mastered == 1
    assert s.quizzes == 2 and round(s.quiz_avg) == round((75 + 100) / 2)
    assert s.commits == 2

    monkeypatch.setattr(settings, "github_owner_login", "ME")          # only my commits, any case
    assert stats.compute(week, "week", FRI27).commits == 1


def test_month_one_targets_are_shown_during_the_first_30_days(week):
    s = stats.compute(week, "month", FRI27)
    assert s.month1 == {"kundalik kunlari": (5, 25), "so'zlar": (0, 200)}
    assert "🎯 1-oy maqsadi: kundalik kunlari 5/25 · so'zlar 0/200" in stats.stats_text(s)
    assert stats.compute(week, "month", dt.date(2026, 12, 25)).month1 is None   # after month 1
    assert stats.compute(week, "week", FRI27).month1 is None


# ── text ──────────────────────────────────────────────────────────────

def test_stats_text_for_a_week(week):
    out = stats.stats_text(stats.compute(week, "week", FRI27))
    assert "Bu hafta (23-noy – 26-noy)" in out
    assert "Jami: 4 s 25 d · Faol kunlar: 2/4 (50%)" in out
    assert "Python 3 s 10 d" in out and "English 0 s 45 d" in out
    assert "AI'siz: 2 s 0 d" in out
    assert "Ketma-ket: 0 kun (eng uzun: 4)" in out
    assert "Bo'sh kunlar: 24-noy, 26-noy" in out
    assert "+10%" in out
    assert "O'rtacha: 2 s 12 d / kun · eng yaxshi: 23-noy (2 s 45 d)" in out


def test_streak_text(week):
    out = stats.streak_text(week, FRI27)
    assert "Hozirgi ketma-ketlik: 0 kun" in out and "Eng uzun: 4 kun" in out
    assert "Barqarorlik: 5/7 kun (71%)" in out
    assert "So'nggi bo'sh kunlar: 24-noy, 26-noy" in out


def test_minutes_format():
    assert stats.fmt_min(0) == "0 s 0 d" and stats.fmt_min(285) == "4 s 45 d"


# ── commands ──────────────────────────────────────────────────────────

class P:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return f"ECHO: {prompt}"


def say(db, text):
    return tb.handle_message(db, P(), text)


def cbs(r):
    return [d for row in r.rows for _, d in row]


def test_stats_command_empty_state_points_to_the_photo(db):
    r = say(db, "/stats")
    assert "Hali kundalik yozuv yo'q" in r.text and cbs(r) == ["do:/photo"]
    assert cbs(say(db, "/streak")) == ["do:/photo"]


def test_stats_command_periods_and_buttons(db, monkeypatch):
    today = study.local_today()
    monkeypatch.setattr(settings, "stats_start_date", (today - dt.timedelta(days=10)).isoformat())
    paper(db, today - dt.timedelta(days=1), python=60, ai_off=30)
    paper(db, today, python=30)

    r = say(db, "/stats")                                         # bare = week
    assert "Bu hafta" in r.text
    assert cbs(r) == ["do:/stats day", "do:/stats month", "do:/stats year"]   # the other periods

    for word, title in [("day", "Bugun"), ("kun", "Bugun"), ("oy", "Bu oy"), ("month", "Bu oy"), ("yil", "Yil")]:
        out = say(db, f"/stats {word}")
        assert title in out.text, (word, out.text)
        assert f"do:/stats {views.PERIOD_WORDS[word]}" not in cbs(out)     # never offers the period being shown
    assert "Foydalanish" in say(db, "/stats nonsense").text

    out = say(db, "/streak")
    assert "Hozirgi ketma-ketlik: 2 kun" in out.text and out.rows


def test_stats_github_keeps_the_old_meaning(db):
    out = say(db, "/stats github")
    assert "Commits" in out.text and "Hodisalar" in out.text      # the GitHub weekly summary


def test_day_stats_with_nothing_yet_asks_for_the_photo(db, monkeypatch):
    today = study.local_today()
    monkeypatch.setattr(settings, "stats_start_date", (today - dt.timedelta(days=3)).isoformat())
    paper(db, today - dt.timedelta(days=1), python=60)
    r = say(db, "/stats day")
    assert "Bugun hali yozuv yo'q" in r.text and cbs(r)[0] == "do:/photo"
