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
