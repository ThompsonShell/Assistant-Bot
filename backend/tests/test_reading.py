import datetime as dt

from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.integrations.news import NewsItem
from app.jobs import study_reminders as sr
from app.jobs import telegram_bot as tb
from app.models.study import DiaryEntry, ReadingLog, VocabCard
from app.study import reading
from app.study import service as study

MON, TUE, FRI, SUN = (dt.date(2026, 11, d) for d in (16, 17, 20, 22))


def _sm():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)


class NoAI:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return "AI yo'q"


class Teacher(NoAI):
    ai_available = True

    def chat(self, prompt, *, system=None, history=None):
        return "Grammatika to'g'ri. Asosiy g'oya aytilgan."


def _item(title, link, summary=""):
    return NewsItem(title=title, link=link, source="ex.com", summary=summary)


def _offline(monkeypatch, tech=(), space=(), words=600):
    """No network: fixed feed items and a fixed article length."""
    monkeypatch.setattr(reading, "fetch_feed_items", lambda urls, http: list(tech))
    monkeypatch.setattr(reading, "fetch_news", lambda limit=8, http=None, topic="tech": list(space))
    monkeypatch.setattr(reading, "estimate_words", lambda url, http: words)


# ── schedule ──────────────────────────────────────────────────────────

def test_weekly_schedule_and_next_day():
    assert [reading.assignment_kind(d) for d in (MON, TUE, FRI, SUN)] == ["vocab", None, "tech", "space"]
    assert reading.next_reading_day(MON) == (FRI, "tech")
    assert reading.next_reading_day(FRI) == (SUN, "space")
    assert reading.next_reading_day(SUN) == (dt.date(2026, 11, 23), "vocab")


def test_target_words_grow_from_month_three():
    start = dt.date(2026, 1, 1)
    assert reading.target_words(start, start) == (400, 800)
    assert reading.target_words(start, start + dt.timedelta(days=59)) == (400, 800)
    assert reading.target_words(start, start + dt.timedelta(days=60)) == (800, 1500)


def test_resources_follow_topic():
    names = lambda t: [n for n, _, _ in reading.resources_for(t)]
    assert names("pytest") == ["Real Python"]
    assert "Django docs" in names("Django ORM") and "Real Python" in names("Django ORM")
    assert "PostgreSQL docs" in names("SQL joins")
    assert "Missing Semester" in names("git branches")
    assert all(is_doc for n, _, is_doc in reading.resources_for("sql") if n != "Real Python")


# ── picking articles ──────────────────────────────────────────────────

def test_topic_score_is_whole_word():
    it = _item("Testing with pytest fixtures", "u", "Learn pytest basics")
    assert reading.topic_score(it, "pytest") == 1
    assert reading.topic_score(it, "pytest fixtures") == 2
    assert reading.topic_score(_item("Contest results", "u"), "test") == 0   # no substring match


def test_pick_article_respects_length_and_skips_read(monkeypatch):
    lengths = {"short": 150, "good": 600, "long": 5000}
    monkeypatch.setattr(reading, "estimate_words", lambda url, http: lengths[url])
    items = [_item("a", "short"), _item("b", "long"), _item("c", "good")]
    item, n = reading.pick_article(items, 400, 800, set(), http=None)
    assert (item.link, n) == ("good", 600)
    # Already read -> skipped; nothing fits -> falls back to the first unread one.
    item, n = reading.pick_article(items, 400, 800, {"good"}, http=None)
    assert (item.link, n) == ("short", None)
    assert reading.pick_article(items, 400, 800, {"short", "long", "good"}, http=None) == (None, None)


# ── /read ─────────────────────────────────────────────────────────────

def test_read_space_creates_log_and_is_idempotent(monkeypatch):
    _offline(monkeypatch, space=[_item("Artemis update", "https://nasa.example/a", "Crew named for the mission.")])
    db = _sm()()
    out = tb.handle_text(db, NoAI(), "/read space")
    assert "Kosmos" in out and "Artemis update" in out and "https://nasa.example/a" in out
    assert "400–800 so'z" in out and "/summary" in out and f"ko'pi bilan {reading.WORD_CAP}" in out
    assert db.query(ReadingLog).count() == 1

    again = tb.handle_text(db, NoAI(), "/read space")
    assert "allaqachon boshlangan" in again and db.query(ReadingLog).count() == 1


def test_read_does_not_repeat_an_article(monkeypatch):
    items = [_item("First", "u1"), _item("Second", "u2")]
    _offline(monkeypatch, space=items)
    db = _sm()()
    tb.handle_text(db, NoAI(), "/read space")
    tb.handle_text(db, NoAI(), "/summary This article explains x. The main idea is y.")
    out = tb.handle_text(db, NoAI(), "/read space")
    assert "Second" in out and "First" not in out


def test_read_tech_matches_weekly_topic(monkeypatch):
    tech = [
        _item("Intro to decorators", "u/dec", "Python decorators"),
        _item("Testing with pytest", "u/pytest", "Write tests using pytest fixtures"),
    ]
    _offline(monkeypatch, tech=tech)
    db = _sm()()
    assert "pytest" in tb.handle_text(db, NoAI(), "/topic pytest")
    out = tb.handle_text(db, NoAI(), "/read tech")
    assert "Testing with pytest" in out and "decorators" not in out
    assert "/tried" in out                       # docs/technical: try an example


def test_read_tech_without_match_offers_sources(monkeypatch):
    _offline(monkeypatch, tech=[_item("Unrelated news", "u/x")])
    db = _sm()()
    tb.handle_text(db, NoAI(), "/topic Django ORM")
    out = tb.handle_text(db, NoAI(), "/read tech")
    assert "Django docs" in out and "Real Python" in out


def test_read_vocab_and_free_day(monkeypatch):
    db = _sm()()
    assert "Reading & Words" in tb.handle_text(db, NoAI(), "/read vocab")

    monkeypatch.setattr(study, "local_today", lambda: TUE)
    out = tb.handle_text(_sm()(), NoAI(), "/read")
    assert "reading kuni emas" in out and "juma" in out and "texnik" in out.lower()


def test_read_uses_todays_planned_kind(monkeypatch):
    _offline(monkeypatch, space=[_item("Sunday story", "u/s")])
    monkeypatch.setattr(study, "local_today", lambda: SUN)
    out = tb.handle_text(_sm()(), NoAI(), "/read")
    assert "Sunday story" in out


# ── words cap, summary, tried ─────────────────────────────────────────

def test_word_cap_during_reading(monkeypatch):
    db = _sm()()
    tb.handle_text(db, NoAI(), "/read vocab")
    out = tb.handle_text(db, NoAI(), "/word\na1 - bir\na2 - ikki\na3 - uch\na4 - to'rt")
    assert "(4/5)" in out
    out = tb.handle_text(db, NoAI(), "/word\na5 - besh\na6 - olti\na7 - yetti")
    assert "(5/5)" in out and "2 ta so'z o'tkazib yuborildi" in out
    assert db.query(VocabCard).count() == 5

    out = tb.handle_text(db, NoAI(), "/word a8 - sakkiz")
    assert "limit to'ldi" in out and db.query(VocabCard).count() == 5


def test_words_are_uncapped_without_open_reading():
    db = _sm()()
    tb.handle_text(db, NoAI(), "/word\n" + "\n".join(f"w{i} - m{i}" for i in range(8)))
    assert db.query(VocabCard).count() == 8


def test_summary_saves_feedback_and_diary(monkeypatch):
    _offline(monkeypatch, space=[_item("Moon base", "u/m")])
    db = _sm()()
    assert "Ochiq o'qish yo'q" in tb.handle_text(db, NoAI(), "/summary hello")
    tb.handle_text(db, NoAI(), "/read space")
    tb.handle_text(db, NoAI(), "/word moon - oy")

    out = tb.handle_text(db, NoAI(), "/summary This article explains the moon base. The main idea is long stays.")
    assert "Xulosa saqlandi" in out and "1/5" in out
    assert "Reja 2 ta gap" not in out and "bilan boshlang" not in out   # a good summary gets no hints
    log = db.query(ReadingLog).one()
    assert log.status == "done" and "moon base" in log.summary
    diary = db.query(DiaryEntry).one()
    assert "[Reading] Moon base" in diary.recalled


def test_summary_hints_and_ai_feedback(monkeypatch):
    _offline(monkeypatch, space=[_item("Mars", "u/mars")])
    db = _sm()()
    tb.handle_text(db, NoAI(), "/read space")
    out = tb.handle_text(db, Teacher(), "/summary Mars is red.")
    assert "sizda 1 ta" in out and "The main idea is" in out    # structure hints
    assert "Grammatika to'g'ri" in out                          # AI feedback appended


def test_tried_and_readlog(monkeypatch):
    _offline(monkeypatch, tech=[_item("pytest guide", "u/p", "pytest")])
    db = _sm()()
    assert "Hali texnik o'qish yo'q" in tb.handle_text(db, NoAI(), "/tried")
    assert "Hali o'qish yo'q" in tb.handle_text(db, NoAI(), "/readlog")

    tb.handle_text(db, NoAI(), "/read tech")
    tb.handle_text(db, NoAI(), "/summary This article explains pytest. The main idea is fixtures.")
    assert "Misolni sinadingiz" in tb.handle_text(db, NoAI(), "/tried")
    log = tb.handle_text(db, NoAI(), "/readlog")
    assert "✅" in log and "tech" in log and "💻" in log


# ── reminders ─────────────────────────────────────────────────────────

class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append(json or {})


def test_reading_reminder_only_on_reading_days_until_done(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "study_enabled", True)
    sm = _sm()
    http = Http()

    monkeypatch.setattr(study, "local_today", lambda: TUE)
    assert sr.remind_reading(sm, http) is False and http.calls == []

    monkeypatch.setattr(study, "local_today", lambda: FRI)
    assert sr.remind_reading(sm, http) is True
    assert "Texnik maqola" in http.calls[-1]["text"] and "/read" in http.calls[-1]["text"]

    with sm() as db:   # finish today's technical reading
        db.add(ReadingLog(day=FRI, kind="tech", title="t", status="done"))
        db.commit()
    assert sr.remind_reading(sm, http) is False
