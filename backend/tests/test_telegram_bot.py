import datetime as dt

from app.db import Base, make_engine, make_sessionmaker
from app.jobs import telegram_bot as tb
from app.models.github import GitHubEvent, GitHubRepo


class FakeProvider:
    ai_available = True

    def chat(self, prompt, *, system=None, history=None):
        return f"ECHO: {prompt}"

    def summarize(self, *a, **k):
        return ""

    def plan(self, *a, **k):
        return None

    def plan_tasks(self, instruction, *, context=None):
        from app.providers.base import PlanResult

        return PlanResult(
            summary="Haftalik reja",
            tasks=[
                {"title": "Backend", "day": "Monday", "duration_minutes": 90, "priority": "high", "category": None},
                {"title": "English", "day": "Tuesday", "duration_minutes": 45, "priority": "medium", "category": None},
            ],
            ai_generated=True,
        )


def _sessionmaker():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)


class FakeHttp:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, **kw):
        self.sent.append(json or {})


def test_help_and_start():
    db = _sessionmaker()()
    assert "Buyruqlar" in tb.handle_text(db, FakeProvider(), "/help")
    assert "Buyruqlar" in tb.handle_text(db, FakeProvider(), "/start")


def test_commands_empty_db():
    db = _sessionmaker()()
    assert "Commits" in tb.handle_text(db, FakeProvider(), "/today")
    assert "hodisa yo'q" in tb.handle_text(db, FakeProvider(), "/github")
    assert "repo yo'q" in tb.handle_text(db, FakeProvider(), "/repos")


def test_unknown_command():
    db = _sessionmaker()()
    assert "Noma'lum" in tb.handle_text(db, FakeProvider(), "/nope")


def test_free_text_routes_to_provider():
    db = _sessionmaker()()
    assert tb.handle_text(db, FakeProvider(), "salom") == "ECHO: salom"


def test_today_splits_mine_and_overall(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "github_owner_login", "asilbek")
    sm = _sessionmaker()
    db = sm()
    now = dt.datetime.now(dt.timezone.utc)
    # One event by me, one by someone else — same watched repo.
    db.add(GitHubEvent(
        gh_id="m1", repo_full_name="o/r", type="PullRequestEvent", actor_login="asilbek",
        actor_type="human", title="opened pr", created_at=now, ingested_at=now,
    ))
    db.add(GitHubEvent(
        gh_id="o1", repo_full_name="o/r", type="PullRequestEvent", actor_login="someone",
        actor_type="human", title="opened pr", created_at=now, ingested_at=now,
    ))
    db.commit()

    out = tb.handle_text(db, FakeProvider(), "/today")
    assert "Mening harakatlarim" in out and "asilbek" in out
    assert "Umumiy" in out
    # Mine: 1 PR; overall: 2 events.
    assert "PR: 1" in out
    assert "Hodisalar: 2" in out


def test_summary_hint_without_owner_login(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "github_owner_login", None)
    db = _sessionmaker()()
    out = tb.handle_text(db, FakeProvider(), "/today")
    assert "Umumiy" in out
    assert "GITHUB_OWNER_LOGIN" in out  # hint to enable the personal split


def test_commands_with_data():
    sm = _sessionmaker()
    db = sm()
    db.add(GitHubRepo(owner="o", name="r", full_name="o/r", active=True))
    db.add(
        GitHubEvent(
            gh_id="1", repo_full_name="o/r", type="Commit", actor_login="alice",
            actor_type="human", title="committed abc",
            created_at=dt.datetime.now(dt.timezone.utc),
            ingested_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()
    assert "o/r" in tb.handle_text(db, FakeProvider(), "/repos")
    assert "alice" in tb.handle_text(db, FakeProvider(), "/github")


def test_effort_command():
    from app.providers.runtime import get_effort

    db = _sessionmaker()()
    assert "effort" in tb.handle_text(db, FakeProvider(), "/effort").lower()
    assert "high" in tb.handle_text(db, FakeProvider(), "/effort high")
    assert get_effort() == "high"
    assert "Noto'g'ri" in tb.handle_text(db, FakeProvider(), "/effort ultra")
    tb.handle_text(db, FakeProvider(), "/effort medium")  # reset for other tests
    assert get_effort() == "medium"


def test_plan_tasks_done_commands():
    from app.models.task import Task

    sm = _sessionmaker()
    db = sm()
    out = tb.handle_text(db, FakeProvider(), "/plan bu hafta backend va ingliz tili")
    assert "Backend" in out and "Saqlandi" in out
    assert db.query(Task).count() == 2

    assert "Backend" in tb.handle_text(db, FakeProvider(), "/tasks")

    tid = db.query(Task).filter(Task.title == "Backend").one().id
    assert "Bajarildi" in tb.handle_text(db, FakeProvider(), f"/done {tid}")
    assert db.get(Task, tid).status == "done"
    # Done tasks drop out of /tasks.
    assert "Backend" not in tb.handle_text(db, FakeProvider(), "/tasks")


def test_weather_command(monkeypatch):
    from app.integrations.weather import Weather

    db = _sessionmaker()()
    fake = Weather(city="Toshkent", temp=18.0, feels_like=16.0, wind=12.0, code=61)
    monkeypatch.setattr(tb, "_weather_text", tb._weather_text)  # keep real formatter
    monkeypatch.setattr("app.integrations.weather.fetch_weather", lambda *a, **k: fake)

    out = tb.handle_text(db, FakeProvider(), "/weather")
    assert "Toshkent" in out
    assert "18°C" in out and "16°C" in out
    assert "Kiyim tavsiyasi" in out
    assert "soyabon" in out.lower()  # rain tip (code 61)


def test_weather_command_handles_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    db = _sessionmaker()()
    monkeypatch.setattr("app.integrations.weather.fetch_weather", boom)
    out = tb.handle_text(db, FakeProvider(), "/weather")
    assert "olib bo'lmadi" in out


def test_owner_only(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    sm = _sessionmaker()

    # Non-owner is rejected.
    http = FakeHttp()
    tb.process_update(
        http, sm, FakeProvider(),
        {"update_id": 1, "message": {"chat": {"id": 111}, "text": "hi"}},
    )
    assert any("shaxsiy bot" in m.get("text", "") for m in http.sent)
    assert not any("ECHO" in m.get("text", "") for m in http.sent)

    # Owner gets a real reply.
    http2 = FakeHttp()
    tb.process_update(
        http2, sm, FakeProvider(),
        {"update_id": 2, "message": {"chat": {"id": 999}, "text": "salom"}},
    )
    assert any("ECHO: salom" in m.get("text", "") for m in http2.sent)
