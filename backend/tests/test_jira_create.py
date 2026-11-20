import base64
import datetime as dt
import json

import httpx
import pytest

from app.bot import jira_flow, state
from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.integrations import jira
from app.jobs import telegram_bot as tb
from app.study import service as study

TOKEN = "ATATT-super-secret-token"
REAL_CLIENT = httpx.Client     # the genuine class, captured before any test patches it


def serve(monkeypatch, handler):
    """Make every Jira call go to ``handler`` instead of the network."""
    monkeypatch.setattr(
        jira.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )


class FakeJira:
    """A pretend Jira Cloud. Records every request."""

    def __init__(self):
        self.requests = []
        self.projects = [{"key": "PRJ", "name": "Practice"}, {"key": "WRK", "name": "Work"}]
        self.issue_types = [
            {"name": "Epic", "subtask": False}, {"name": "Task", "subtask": False},
            {"name": "Sub-task", "subtask": True},
        ]
        self.create_status = 201
        self.create_body = {"key": "PRJ-7"}
        self.create_script = []           # per-POST (status, body); used before the defaults
        self.myself_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body, dict(request.headers)))
        path = request.url.path
        if path == "/rest/api/3/myself":
            if self.myself_status != 200:
                return httpx.Response(self.myself_status, json={"message": "x"})
            return httpx.Response(200, json={"displayName": "Asilbek"})
        if path == "/rest/api/3/project/search":
            return httpx.Response(200, json={"values": self.projects})
        if path.startswith("/rest/api/3/project/"):
            return httpx.Response(200, json={"issueTypes": self.issue_types})
        if path == "/rest/api/3/issue" and request.method == "POST":
            if self.create_script:
                status, body = self.create_script.pop(0)
                return httpx.Response(status, json=body)
            return httpx.Response(self.create_status, json=self.create_body)
        if path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": [
                {"key": "PRJ-1", "fields": {"summary": "Fix", "status": {"name": "To Do",
                 "statusCategory": {"key": "new"}}, "duedate": None, "priority": {"name": "High"}}}]})
        return httpx.Response(404, json={"errorMessages": ["nope"]})

    def posts(self):
        return [r for r in self.requests if r[0] == "POST" and r[1] == "/rest/api/3/issue"]


@pytest.fixture
def fake(monkeypatch):
    f = FakeJira()
    serve(monkeypatch, f)
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "me@example.com")
    monkeypatch.setattr(settings, "jira_api_token", TOKEN)
    monkeypatch.setattr(settings, "jira_project_key", "PRJ")
    monkeypatch.setattr(settings, "jira_issue_type", "Task")
    return f


@pytest.fixture
def db():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)()


class NoAI:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return "ECHO"


def say(db, text):
    return tb.handle_message(db, NoAI(), text)


def cbs(reply):
    return [d for row in reply.rows for _, d in row]


def tap(db, data):
    return jira_flow.on_callback(db, data.split(":"))


# ── the API layer ─────────────────────────────────────────────────────

def test_create_issue_sends_the_right_request(fake):
    created = jira.create_issue("PRJ", "  Write tests  ", due=dt.date(2026, 11, 25),
                                labels=["study"], description="from bot")
    assert (created.key, created.url) == ("PRJ-7", "https://acme.atlassian.net/browse/PRJ-7")

    method, path, body, headers = fake.posts()[0]
    f = body["fields"]
    assert f["project"] == {"key": "PRJ"} and f["summary"] == "Write tests"
    assert f["issuetype"] == {"name": "Task"} and f["duedate"] == "2026-11-25" and f["labels"] == ["study"]
    assert f["description"]["type"] == "doc" and f["description"]["content"][0]["content"][0]["text"] == "from bot"
    expected = base64.b64encode(f"me@example.com:{TOKEN}".encode()).decode()
    assert headers["authorization"] == f"Basic {expected}"
    assert TOKEN not in json.dumps(fake.requests[0][2]) and TOKEN not in fake.requests[0][1]   # never in body or URL


def test_optional_fields_are_left_out(fake):
    jira.create_issue("PRJ", "Plain")
    fields = fake.posts()[0][2]["fields"]
    assert "duedate" not in fields and "labels" not in fields and "description" not in fields


def test_issue_type_falls_back_to_the_first_ordinary_type(fake, monkeypatch):
    fake.issue_types = [{"name": "Story", "subtask": False}, {"name": "Sub-task", "subtask": True}]
    assert jira.pick_issue_type("PRJ") == "Story"
    monkeypatch.setattr(settings, "jira_issue_type", "story")
    assert jira.pick_issue_type("PRJ") == "Story"                      # case-insensitive
    fake.issue_types = [{"name": "Sub-task", "subtask": True}]
    with pytest.raises(jira.JiraError, match="oddiy issue turi"):
        jira.pick_issue_type("PRJ")


@pytest.mark.parametrize("status,body,fragment", [
    (401, {}, "JIRA_API_TOKEN noto'g'ri"),
    (403, {}, "ruxsat yo'q"),
    (404, {}, "JIRA_BASE_URL yoki loyiha kaliti"),
    (400, {"errors": {"duedate": "Invalid date"}, "errorMessages": []}, "duedate: Invalid date"),
])
def test_errors_are_explained(fake, status, body, fragment):
    fake.create_status, fake.create_body = status, body
    with pytest.raises(jira.JiraError) as err:
        jira.create_issue("PRJ", "x")
    assert fragment in err.value.user_message and TOKEN not in err.value.user_message


def test_network_failure_is_explained(monkeypatch, fake):
    def boom(request):
        raise httpx.ConnectError("no route")

    serve(monkeypatch, boom)
    with pytest.raises(jira.JiraError, match="ulanib bo'lmadi"):
        jira.whoami()


def test_base_url_is_forgiving(monkeypatch):
    for raw, expected in [
        ("https://acme.atlassian.net", "https://acme.atlassian.net"),
        ("acme.atlassian.net", "https://acme.atlassian.net"),
        ("  'https://acme.atlassian.net/'  ", "https://acme.atlassian.net"),
        ("https://acme.atlassian.net/jira/software/projects/X/boards/1", "https://acme.atlassian.net"),
    ]:
        monkeypatch.setattr(settings, "jira_base_url", raw)
        assert jira.base_url() == expected, raw


def test_missing_settings_lists_names_only(monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "  ")
    monkeypatch.setattr(settings, "jira_api_token", None)
    assert jira.missing_settings() == ["JIRA_EMAIL", "JIRA_API_TOKEN"] and not jira.is_configured()


# ── reading the request ───────────────────────────────────────────────

def test_parse_task():
    today = study.local_today()
    assert jira_flow.parse_task("Write tests") == ("Write tests", None, [])
    assert jira_flow.parse_task("Write tests ertaga") == ("Write tests", today + dt.timedelta(days=1), [])
    assert jira_flow.parse_task("Write tests BUGUN") == ("Write tests", today, [])
    assert jira_flow.parse_task("Write tests ertaga #study") == (
        "Write tests", today + dt.timedelta(days=1), ["study"])        # a label after the date word
    assert jira_flow.parse_task("Write tests 2026-11-25") == ("Write tests", dt.date(2026, 11, 25), [])
    assert jira_flow.parse_task("CS50P L2 #study #english 2026-12-01") == (
        "CS50P L2", dt.date(2026, 12, 1), ["study", "english"])
    assert jira_flow.parse_task("Release 2026-13-45")[:2] == ("Release 2026-13-45", None)   # not a date: kept
    assert jira_flow.parse_task("ertaga uchrashuv ertaga")[0] == "ertaga uchrashuv"          # only the end counts
    assert jira_flow.parse_task("   ") == ("", None, [])


@pytest.mark.parametrize("text,expected", [
    ("Jira ga task qo'sh: testlar yozish", ("add", "testlar yozish")),
    ("jiraga yangi task yarat: README  ertaga", ("add", "README  ertaga")),
    ("Jira'ga vazifa qo‘sh: SQL JOIN", ("add", "SQL JOIN")),        # typographic apostrophe
    ("Jira ga task qo'sh", ("add", "")),                             # no title: the bot asks
    ("Jira ga issue qo'sh:", ("add", "")),
    ("Add a Jira task: fix bug", ("add", "fix bug")),
    ("Jira ga task qo'sh:\nbirinchi\nikkinchi", ("add", "birinchi\nikkinchi")),
    # The bot's own tasks are meant, not a new title:
    ("Jira ga bugungi vazifalarni qo'sh", ("sync", "")),
    ("barcha tasklarimni jira ga yubor", ("sync", "")),
    # A reply that mentions Jira and says "add" is still a request (it used to fall through to Claude):
    ("Men jirani ulaganman, qo'sh", ("add", "")),
    # Not requests:
    ("jira nima o'zi", None),
    ("Jira ga task qo'shsam bo'ladimi?", None),                      # a question
    ("Jira ga qo'shgan edim", None),                                 # past tense
    ("Jira ga yuborganman", None),
    ("Bugun nima qilay", None),
    ("task qo'sh: testlar", None),                                   # no mention of Jira
    ("/jira add x", None),
])
def test_intent(text, expected):
    assert jira_flow.intent(text) == expected


# ── the guided flow ───────────────────────────────────────────────────

def test_preview_comes_first_and_nothing_is_created_until_yaratish(db, fake):
    r = say(db, "/jira add Write tests ertaga #study")
    assert "yangi task yaratilsinmi" in r.text and "PRJ" in r.text and "Nom: Write tests" in r.text
    assert "🏷 study" in r.text and "#study" not in r.text
    assert "⏰ " + (study.local_today() + dt.timedelta(days=1)).isoformat() in r.text
    assert cbs(r) == ["jc:ok", "jc:proj", "do:/cancel"]
    assert fake.posts() == []                                          # nothing yet

    done = tap(db, "jc:ok")
    assert "PRJ-7" in done.text and "https://acme.atlassian.net/browse/PRJ-7" in done.text
    assert cbs(done) == ["do:/jira"] and len(fake.posts()) == 1
    assert state.get_state(db) is None
    fields = fake.posts()[0][2]["fields"]
    assert fields["summary"] == "Write tests" and fields["labels"] == ["study"]
    assert fields["duedate"] == (study.local_today() + dt.timedelta(days=1)).isoformat()


def test_the_owners_exact_sentence_works(db, fake):
    r = say(db, "Jira ga task qo'sh: testlar yozish")
    assert "Nom: testlar yozish" in r.text and fake.posts() == []
    assert len(fake.posts()) == 0
    assert "PRJ-7" in tap(db, "jc:ok").text and len(fake.posts()) == 1


def test_missing_title_is_asked_then_previewed(db, fake):
    assert "Task nomi nima" in say(db, "Jira ga task qo'sh").text
    assert state.get_state(db)[0] == "jira:title"
    assert "Nom: README yozish" in say(db, "README yozish").text
    assert "Task nomi nima" in say(db, "/jira add").text


def test_typing_in_the_preview_replaces_the_list(db, fake):
    say(db, "/jira add Birinchi nom 2026-12-01")
    r = say(db, "Ikkinchi nom")
    assert "Nom: Ikkinchi nom" in r.text and "2026-12-01" not in r.text     # a new text is a new request
    r = say(db, "Uchinchi nom ertaga")
    assert "Nom: Uchinchi nom" in r.text and (study.local_today() + dt.timedelta(days=1)).isoformat() in r.text
    tap(db, "jc:ok")
    assert fake.posts()[0][2]["fields"]["summary"] == "Uchinchi nom"


def test_cancel_creates_nothing(db, fake):
    say(db, "/jira add x")
    assert "Bekor qilindi" in say(db, "/cancel").text
    assert "eskirgan" in tap(db, "jc:ok").text and fake.posts() == []


def test_a_failed_create_keeps_the_preview_for_a_retry(db, fake):
    say(db, "/jira add Write tests")
    fake.create_status, fake.create_body = 400, {"errors": {"summary": "too long"}}
    r = tap(db, "jc:ok")
    assert "Yaratilmadi" in r.text and "summary: too long" in r.text and "jc:ok" in cbs(r)
    assert state.get_state(db)[0] == "jira:confirm"

    fake.create_status, fake.create_body = 201, {"key": "PRJ-8"}
    assert "PRJ-8" in tap(db, "jc:ok").text


# ── project choice ────────────────────────────────────────────────────

def test_project_is_asked_once_and_remembered(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "jira_project_key", None)
    r = say(db, "/jira add Write tests")
    assert "Qaysi loyihaga" in r.text and "jp:PRJ" in cbs(r) and "jp:WRK" in cbs(r)
    assert fake.posts() == []

    r = tap(db, "jp:WRK")
    assert "Loyiha: WRK" in r.text and "Nom: Write tests" in r.text    # carries on with the task
    tap(db, "jc:ok")
    assert fake.posts()[0][2]["fields"]["project"] == {"key": "WRK"}

    r = say(db, "/jira add Boshqa task")                                # remembered: no question
    assert "Qaysi loyihaga" not in r.text and "Loyiha: WRK" in r.text


def test_the_only_project_is_chosen_automatically(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "jira_project_key", None)
    fake.projects = [{"key": "ONLY", "name": "Only one"}]
    assert "Loyiha: ONLY" in say(db, "/jira add x").text


def test_change_project_from_the_preview_and_the_command(db, fake):
    say(db, "/jira add x")
    assert "jp:WRK" in cbs(tap(db, "jc:proj"))
    r = tap(db, "jp:WRK")
    assert "Loyiha: WRK" in r.text and "Nom: x" in r.text
    assert "jp:PRJ" in cbs(say(db, "/jira project"))
    assert "Loyiha: PRJ" in tap(db, "jp:PRJ").text and "Nom:" not in tap(db, "jp:PRJ").text.split("\n")[0]


def test_project_list_failure_points_to_the_env_setting(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "jira_project_key", None)

    def broken(request):
        if request.url.path == "/rest/api/3/project/search":
            return httpx.Response(403, json={})
        return fake(request)

    serve(monkeypatch, broken)
    r = say(db, "/jira add x")
    assert "ruxsat yo'q" in r.text and "JIRA_PROJECT_KEY=" in r.text


# ── not connected / diagnostics ───────────────────────────────────────

def test_not_connected_names_what_is_missing_without_showing_values(db, monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", None)
    monkeypatch.setattr(settings, "jira_api_token", TOKEN)
    for text in ("/jira", "/jira add x", "/jira status", "Jira ga task qo'sh: x"):
        r = say(db, text)
        assert "Jira ulanmagan" in r.text and "JIRA_EMAIL" in r.text, text
        assert "JIRA_BASE_URL" not in r.text.split("Yetishmayotgan sozlamalar:")[1].split("\n")[0]
        assert TOKEN not in r.text and "acme.atlassian.net" not in r.text
        assert "Assistant-Bot/.env" in r.text and "run-local.sh" in r.text


def test_status_proves_the_connection_or_explains(db, fake):
    r = say(db, "/jira status")
    assert "Jira ulangan: Asilbek" in r.text and "Loyiha: PRJ" in r.text
    fake.myself_status = 401
    r = say(db, "/jira status")
    assert "Jira ulanmadi" in r.text and "JIRA_API_TOKEN noto'g'ri" in r.text and TOKEN not in r.text


def test_the_issue_list_shows_the_real_reason_when_it_fails(db, fake, monkeypatch):
    assert "PRJ-1" in say(db, "/jira").text
    serve(monkeypatch, lambda request: httpx.Response(401, json={}))
    out = say(db, "/jira").text
    assert "JIRA_API_TOKEN noto'g'ri" in out and TOKEN not in out


# ── through Telegram ──────────────────────────────────────────────────

class Http:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, **kw):
        self.posts.append((url.rsplit("/", 1)[-1], json or {}))


def test_create_button_through_telegram_and_strangers_are_ignored(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    engine = db.get_bind()
    sm = make_sessionmaker(engine)
    http = Http()

    def msg(text):
        return {"message": {"chat": {"id": 999}, "text": text}}

    def button(data, chat=999):
        return {"callback_query": {"id": "c", "data": data, "message": {"message_id": 5, "chat": {"id": chat}}}}

    tb.process_update(http, sm, NoAI(), msg("Jira ga task qo'sh: testlar yozish"))
    preview = http.posts[-1][1]
    assert [b["callback_data"] for row in preview["reply_markup"]["inline_keyboard"] for b in row][0] == "jc:ok"

    tb.process_update(http, sm, NoAI(), button("jc:ok", chat=111))     # stranger
    assert fake.posts() == []

    n = len(http.posts)
    tb.process_update(http, sm, NoAI(), button("jc:ok"))
    sent = http.posts[n:]
    assert any(m == "editMessageReplyMarkup" and p["reply_markup"] == {"inline_keyboard": []} for m, p in sent)
    assert any(m == "sendMessage" and "PRJ-7" in p["text"] for m, p in sent)
    assert len(fake.posts()) == 1

    tb.process_update(http, sm, NoAI(), button("jc:ok"))               # a second tap finds nothing to create
    assert len(fake.posts()) == 1


# ── several tasks at once ─────────────────────────────────────────────

def test_parse_items_lines_bullets_and_limit():
    items = jira_flow.parse_items("- Write tests ertaga #study\n2. Read article; SQL JOIN 2026-12-01\n\n  \n")
    assert [i["title"] for i in items] == ["Write tests", "Read article", "SQL JOIN"]
    assert items[0]["labels"] == ["study"] and items[2]["due"] == "2026-12-01" and items[1]["due"] is None
    assert jira_flow.parse_items("") == [] and jira_flow.parse_items("  \n ; ") == []
    many = jira_flow.parse_items("\n".join(f"task {i}" for i in range(30)))
    assert len(many) == jira_flow.MAX_ITEMS


def test_several_lines_make_several_tasks(db, fake):
    r = say(db, "/jira add\nWrite tests ertaga\nRead article #english\nSQL JOIN")
    assert "3 ta task yaratilsinmi" in r.text
    assert "1. Write tests · ⏰" in r.text and "2. Read article · 🏷 english" in r.text and "3. SQL JOIN" in r.text
    assert fake.posts() == []

    done = tap(db, "jc:ok")
    assert [p[2]["fields"]["summary"] for p in fake.posts()] == ["Write tests", "Read article", "SQL JOIN"]
    assert done.text.count("✅ Jira'da yaratildi") == 3 and "Write tests" in done.text
    assert state.get_state(db) is None


def test_a_multi_line_sentence_in_plain_words(db, fake):
    r = say(db, "Jira ga bugungi tasklarni qo'sh:\nPython lecture\nIngliz tili lecture\nGitHub: 10 ta action")
    assert "3 ta task yaratilsinmi" in r.text and "3. GitHub: 10 ta action" in r.text


def test_when_one_of_several_fails_only_that_one_is_retried(db, fake):
    say(db, "/jira add\nBirinchi\nIkkinchi\nUchinchi")
    fake.create_script = [(201, {"key": "PRJ-1"}), (400, {"errors": {"summary": "bad"}}), (201, {"key": "PRJ-3"})]
    r = tap(db, "jc:ok")
    assert "PRJ-1" in r.text and "PRJ-3" in r.text and "Yaratilmadi: Ikkinchi" in r.text and "summary: bad" in r.text
    assert state.get_state(db)[1]["items"][0]["title"] == "Ikkinchi" and len(state.get_state(db)[1]["items"]) == 1

    fake.create_script = [(201, {"key": "PRJ-2"})]
    assert "PRJ-2" in tap(db, "jc:ok").text
    assert len(fake.posts()) == 4                                   # 3 first, then only the failed one
    assert state.get_state(db) is None


# ── sending the bot's own tasks ───────────────────────────────────────

def _tasks(db):
    from app.models.task import Task

    today = study.local_today()
    rows = [
        Task(title="Today task", scheduled_date=today),
        Task(title="Overdue task", scheduled_date=today - dt.timedelta(days=2)),
        Task(title="Undated task"),
        Task(title="Future task", scheduled_date=today + dt.timedelta(days=3)),
        Task(title="Finished task", scheduled_date=today, status="done"),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def test_sync_sends_open_due_tasks_once(db, fake):
    from app.models.task import JiraLink

    _tasks(db)
    r = say(db, "/jira sync")
    assert "3 ta task yaratilsinmi" in r.text
    for title in ("Today task", "Overdue task", "Undated task"):
        assert title in r.text
    assert "Future task" not in r.text and "Finished task" not in r.text
    assert fake.posts() == []

    done = tap(db, "jc:ok")
    assert done.text.count("✅") == 3 and len(fake.posts()) == 3
    assert db.query(JiraLink).count() == 3

    again = say(db, "/jira sync")                                    # nothing new to send
    assert "yuboriladigan vazifa yo'q" in again.text and "do:/plan" in cbs(again)
    assert len(fake.posts()) == 3


def test_sync_in_plain_words_and_with_a_new_task_in_between(db, fake):
    _tasks(db)
    say(db, "/jira sync")
    tap(db, "jc:ok")
    from app.models.task import Task

    db.add(Task(title="New one", scheduled_date=study.local_today()))
    db.commit()
    r = say(db, "Jira ga bugungi vazifalarni qo'sh")
    assert "Nom: New one" in r.text and "Today task" not in r.text   # only the new task


def test_a_failed_sync_item_is_not_marked_as_sent(db, fake):
    from app.models.task import JiraLink

    _tasks(db)
    say(db, "/jira sync")
    fake.create_script = [(201, {"key": "PRJ-1"}), (403, {}), (201, {"key": "PRJ-3"})]
    tap(db, "jc:ok")
    assert db.query(JiraLink).count() == 2
    # Order is overdue, today, undated: the 2nd one ("Today task") failed and is the only one offered again.
    r = say(db, "/jira sync")
    assert "Nom: Today task" in r.text and "Overdue task" not in r.text and "Undated task" not in r.text


def test_sync_when_jira_is_not_connected(db, monkeypatch):
    monkeypatch.setattr(settings, "jira_api_token", None)
    _tasks(db)
    assert "JIRA_API_TOKEN" in say(db, "/jira sync").text
    assert "JIRA_API_TOKEN" in say(db, "Jira ga bugungi vazifalarni qo'sh").text


def test_links_live_in_their_own_table_so_old_databases_keep_working():
    from app.models.task import Task

    assert "jira_key" not in Task.__table__.columns                 # tasks is never altered


# ── what Claude is told ───────────────────────────────────────────────

def test_claude_is_told_the_real_jira_state_and_the_commands(db, fake, monkeypatch):
    from app.bot import memory

    prompt = memory.system_prompt(db, "BASE")
    assert "Jira is CONNECTED" in prompt and "/jira add" in prompt and "/jira sync" in prompt
    assert "never invent CSV imports" in prompt

    monkeypatch.setattr(settings, "jira_email", None)
    prompt = memory.system_prompt(db, "BASE")
    assert "NOT connected (missing JIRA_EMAIL)" in prompt


def test_the_message_that_used_to_reach_claude_now_reaches_the_jira_flow(db, fake):
    class Claude:
        ai_available = True
        calls = 0

        def chat(self, *a, **k):
            Claude.calls += 1
            return "Jira'ga ulanmaganman"

    r = tb.handle_message(db, Claude(), "Men jirani ulaganman, qo'sh")
    assert "Task nomi nima" in r.text and Claude.calls == 0         # asked for the title, no guessing
