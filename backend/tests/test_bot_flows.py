import datetime as dt

import pytest

from app.bot import registry, state
from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.jobs import telegram_bot as tb
from app.models.bot_state import ConversationState
from app.models.study import DiaryEntry, ReadingLog, VocabCard
from app.models.task import Task
from app.providers.base import PlanResult
from app.study import service as study


class Provider:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return f"ECHO: {prompt}"

    def plan_tasks(self, instruction, *, context=None):
        return PlanResult(summary="Reja", tasks=[{"title": "Backend", "day": "Monday"}], ai_generated=True)


def _sm():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)


@pytest.fixture
def db():
    return _sm()()


def say(db, text):
    return tb.handle_message(db, Provider(), text)


def buttons(reply):
    return [(label, data) for row in reply.rows for label, data in row]


def callbacks(reply):
    return [data for _, data in buttons(reply)]


# ── guided conversations ──────────────────────────────────────────────

def test_bare_word_asks_then_saves_then_confirms(db):
    r = say(db, "/word")
    assert "Qaysi so'z" in r.text
    assert callbacks(r) == ["do:/cancel"]                 # always a way out
    assert state.get_state(db)[0] == "flow:/word"

    r = say(db, "abide - rioya qilmoq")
    assert "Qo'shildi: 1" in r.text
    assert state.get_state(db) is None                     # flow finished
    assert db.query(VocabCard).one().word == "abide"
    assert buttons(r)                                      # ends with a next action


def test_one_message_form_still_works(db):
    r = say(db, "/word abide - rioya qilmoq")
    assert "Qo'shildi: 1" in r.text and state.get_state(db) is None
    assert "Qo'shildi: 1" in say(db, "/word\nfoo - bar").text   # multi-line form too


def test_bad_answer_asks_again(db):
    say(db, "/word")
    r = say(db, "faqat so'z, ma'nosiz")
    assert "Format" in r.text and "Qaysi so'z" in r.text      # hint + same question
    assert state.get_state(db)[0] == "flow:/word"             # still waiting
    assert db.query(VocabCard).count() == 0
    assert "Qo'shildi" in say(db, "abide - rioya qilmoq").text


@pytest.mark.parametrize("cmd,question,field", [
    ("/learned", "nimani o'rgandingiz", "learned"),
    ("/recall", "esingizda qolganini", "recalled"),
])
def test_diary_flows_save_to_todays_entry(db, cmd, question, field):
    assert question in say(db, cmd).text
    say(db, "list comprehension")
    entry = db.query(DiaryEntry).one()
    assert getattr(entry, field) == "list comprehension"


def test_topic_and_drill_flows(db):
    assert "mavzu" in say(db, "/topic").text.lower()
    assert "pytest" in say(db, "pytest").text
    assert "mashq" in say(db, "/drill").text.lower()
    assert "Claude ulangan" in say(db, "python lists").text   # no AI in this provider


def test_plan_flow_runs_the_planner(db):
    assert "Qanday reja" in say(db, "/plan").text
    out = say(db, "bu hafta backend").text
    assert "Backend" in out and db.query(Task).count() == 1


def test_done_flow_validates_the_number(db):
    r = say(db, "/done")
    assert "Vazifa yo'q" in r.text and callbacks(r) == ["do:/plan"]   # empty state, no question

    db.add(Task(title="Write tests"))
    db.commit()
    tid = db.query(Task).one().id
    assert "vazifa raqami" in say(db, "/done").text
    assert "Raqam yozing" in say(db, "hozir qilaman").text
    assert state.get_state(db) is not None
    assert "Bajarildi" in say(db, f"#{tid}").text
    assert db.get(Task, tid).status == "done"


def test_summary_without_open_reading_skips_the_question(db):
    r = say(db, "/summary")
    assert "Ochiq o'qish yo'q" in r.text and callbacks(r) == ["do:/read"]
    assert state.get_state(db) is None

    db.add(ReadingLog(day=study.local_today(), kind="space", title="Moon", status="open"))
    db.commit()
    assert "ingliz tilida" in say(db, "/summary").text
    assert "Xulosa saqlandi" in say(db, "This article explains the moon. The main idea is stay.").text


# ── leaving a flow ────────────────────────────────────────────────────

def test_a_new_command_cancels_the_pending_question(db):
    say(db, "/word")
    say(db, "/tasks")                                   # different command
    assert state.get_state(db) is None
    assert say(db, "salom").text == "ECHO: salom"       # chat, not saved as a word
    assert db.query(VocabCard).count() == 0


def test_cancel_command_and_button(db):
    say(db, "/learned")
    r = say(db, "/cancel")
    assert "Bekor qilindi" in r.text and state.get_state(db) is None
    assert callbacks(r) == ["do:/menu"]
    assert "Bekor qilinadigan narsa yo'q" in say(db, "/cancel").text


def test_forgotten_question_expires(db):
    say(db, "/learned")
    row = db.get(ConversationState, state.KEY)
    row.updated_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    db.commit()
    assert say(db, "salom").text == "ECHO: salom"       # not swallowed as a diary entry
    assert db.query(DiaryEntry).count() == 0


# ── menu ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["/start", "/help", "start", "🏠 Menyu"])
def test_start_and_help_show_the_main_menu(db, text):
    r = say(db, text)
    labels = [l for l, _ in buttons(r)]
    assert [l.split(" ", 1)[1] for l in labels] == [
        "Bugun", "Kundalik", "So'z qo'shish", "Takrorlash", "Imtihon", "Statistika", "Yana",
    ]
    assert "Asosiy menyu" in r.text and "Takrorlash" in r.text
    assert len(r.text) < 300                              # short, not the 20-command wall


def test_yana_lists_every_visible_command(db, monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", None)
    monkeypatch.setattr(settings, "watch_channels", "")
    r = say(db, "/more")
    for name in ("word", "review", "plan", "today", "weather", "diary", "quiz"):
        assert f"/{name} " in r.text
    assert "do:/menu" in callbacks(r)


def test_unconfigured_features_are_hidden_until_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", None)
    monkeypatch.setattr(settings, "watch_channels", "")
    names = {c["command"] for c in registry.telegram_menu()}
    assert "jira" not in names and "channels" not in names and "word" in names
    more = say(db, "/more")
    assert "/jira" not in more.text and "/channels" not in more.text
    assert "do:/jira" not in callbacks(more) and "do:/channels" not in callbacks(more)
    assert "WATCH_CHANNELS" in say(db, "/channels").text       # typing it still explains

    monkeypatch.setattr(settings, "jira_base_url", "https://x.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "a@b.c")
    monkeypatch.setattr(settings, "jira_api_token", "t")
    monkeypatch.setattr(settings, "watch_channels", "techchan")
    names = {c["command"] for c in registry.telegram_menu()}
    assert {"jira", "channels"} <= names
    more = say(db, "/more")
    assert "/jira " in more.text and "do:/jira" in callbacks(more) and "do:/channels" in callbacks(more)


def test_hidden_news_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "news_enabled", False)
    assert "news" not in {c["command"] for c in registry.telegram_menu()}


# ── empty states and the next action ──────────────────────────────────

@pytest.mark.parametrize("cmd,expect", [
    ("/words", "do:/word"), ("/tasks", "do:/plan"), ("/readlog", "do:/read"),
    ("/quiz", "do:/word"), ("/github", "do:/github week"),
])
def test_empty_states_offer_the_fixing_button(db, cmd, expect):
    r = say(db, cmd)
    assert callbacks(r) == [expect], r.text


def test_every_reply_ends_with_an_action(db):
    for cmd in ("/words", "/tasks", "/github", "/repos", "/readlog", "/tried", "/quiz",
                "/effort", "/diary", "/today", "/nonsense", "plain chat text"):
        assert buttons(say(db, cmd)), cmd


def test_best_next_action_priority(db):
    assert callbacks(say(db, "/effort")) == ["do:/diary"]        # nothing due, diary still empty

    study.add_words(db, "abide - rioya qilmoq")                  # a card is due now
    assert callbacks(say(db, "/effort")) == ["do:/review"]
    assert "Takrorlash (1)" in buttons(say(db, "/effort"))[0][0]
    # The command just run is never suggested again.
    assert callbacks(say(db, "/review")) != ["do:/review"]

    say(db, "/quiz")                                             # a running quiz comes first
    assert callbacks(say(db, "/effort")) == ["do:/quiz stop"]


def test_best_next_falls_back_to_the_menu(db):
    today = study.local_today()
    study.add_words(db, "abide - rioya qilmoq")
    study.rate_card(db, db.query(VocabCard).one().id, "good", today)   # nothing due
    study.append_diary(db, "learned", "x")
    study.append_diary(db, "recalled", "y")                      # words added today -> diary complete
    assert callbacks(say(db, "/effort")) == ["do:/menu"]


def test_bugun_overview(db):
    db.add(Task(title="Write tests"))
    db.commit()
    study.add_words(db, "abide - rioya qilmoq")
    r = say(db, "/bugun")
    assert "Write tests" in r.text and "Takrorlash: 1" in r.text and "Kundalik" in r.text
    assert buttons(r)


# ── through process_update (what Telegram actually sends) ─────────────

class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append((url.rsplit("/", 1)[-1], json or {}))


def _msg(text, chat=999):
    return {"message": {"chat": {"id": chat}, "text": text}}


def _cb(data, chat=999):
    return {"callback_query": {"id": "c", "data": data, "message": {"message_id": 1, "chat": {"id": chat}}}}


def test_start_sends_menu_button_then_inline_menu(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    sm, http = _sm(), Http()
    tb.process_update(http, sm, Provider(), _msg("/start"))
    sent = [c for c in http.calls if c[0] == "sendMessage"]
    assert sent[0][1]["reply_markup"]["keyboard"][0][0]["text"] == "🏠 Menyu"
    inline = sent[1][1]["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for row in inline for b in row][:2] == ["do:/bugun", "do:/diary"]


def test_menu_button_starts_a_flow_and_the_next_message_completes_it(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    sm, http = _sm(), Http()
    tb.process_update(http, sm, Provider(), _cb("do:/word"))
    assert "Qaysi so'z" in http.calls[-1][1]["text"]
    tb.process_update(http, sm, Provider(), _msg("abide - rioya qilmoq"))
    assert "Qo'shildi: 1" in http.calls[-1][1]["text"]
    with sm() as db:
        assert db.query(VocabCard).count() == 1


def test_do_buttons_from_strangers_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    sm, http = _sm(), Http()
    tb.process_update(http, sm, Provider(), _cb("do:/word", chat=111))
    assert all(c[0] == "answerCallbackQuery" for c in http.calls)
    with sm() as db:
        assert state.get_state(db) is None
