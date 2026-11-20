import json
import subprocess
from types import SimpleNamespace

import pytest

from app.bot import memory
from app.db import Base, make_engine, make_sessionmaker
from app.jobs import telegram_bot as tb
from app.models.conversation import ChatMessage, MemoryFact
from app.providers.claude_agent import ClaudeAgentProvider
from app.study import service as study


class Claude:
    """Records what Claude would receive; answers with a numbered reply."""

    ai_available = True

    def __init__(self):
        self.calls = []

    def chat(self, prompt, *, system=None, history=None):
        self.calls.append({"prompt": prompt, "system": system, "history": history})
        return f"javob {len(self.calls)}"


class NoAI:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return "AI chat hali ulanmagan"


@pytest.fixture
def engine():
    e = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(e)
    return e


@pytest.fixture
def db(engine):
    return make_sessionmaker(engine)()


def say(db, provider, text):
    return tb.handle_message(db, provider, text)


# ── the conversation is remembered ────────────────────────────────────

def test_the_next_message_sees_the_previous_ones(db):
    ai = Claude()
    say(db, ai, "Men Django o'rganyapman")
    say(db, ai, "Qaysi mavzudan boshlay?")

    first, second = ai.calls
    assert first["history"] == []                                  # nothing yet
    assert second["history"] == [
        {"role": "user", "content": "Men Django o'rganyapman"},
        {"role": "assistant", "content": "javob 1"},
    ]
    assert second["prompt"] == "Qaysi mavzudan boshlay?"


def test_memory_survives_a_restart(engine):
    ai = Claude()
    say(make_sessionmaker(engine)(), ai, "Mening maqsadim: junior backend")
    fresh_session = make_sessionmaker(engine)()                    # new process, same database
    say(fresh_session, ai, "Maqsadim nima edi?")
    assert ai.calls[-1]["history"][0]["content"] == "Mening maqsadim: junior backend"


def test_history_is_trimmed_to_a_budget_and_starts_with_the_owner(db):
    for i in range(30):
        db.add(ChatMessage(role="user", content=f"savol {i} " + "x" * 600))
        db.add(ChatMessage(role="assistant", content=f"javob {i} " + "y" * 600))
    db.commit()
    hist = memory.recent_history(db)
    assert 0 < len(hist) <= memory.HISTORY_MESSAGES
    assert sum(len(h["content"]) for h in hist) <= memory.HISTORY_CHARS + memory.MESSAGE_CHARS
    assert hist[0]["role"] == "user" and hist[-1]["content"].startswith("javob 29")   # newest kept
    assert all(len(h["content"]) <= memory.MESSAGE_CHARS for h in hist)


def test_history_never_starts_with_an_assistant_message(db):
    db.add(ChatMessage(role="assistant", content="eski javob"))
    db.add(ChatMessage(role="user", content="savol"))
    db.commit()
    assert [h["role"] for h in memory.recent_history(db)] == ["user"]


def test_errors_and_no_ai_are_not_remembered(db):
    class Broken(Claude):
        def chat(self, prompt, *, system=None, history=None):
            return "⚠️ Claude (obuna) xatosi: timeout"

    say(db, Broken(), "salom")
    say(db, NoAI(), "salom")
    assert db.query(ChatMessage).count() == 0


def test_commands_flows_and_quiz_answers_are_not_chat_history(db):
    ai = Claude()
    say(db, ai, "/word")                    # starts a flow
    say(db, ai, "abide - rioya qilmoq")     # answers it
    say(db, ai, "/tasks")
    study.add_words(db, "foo - bar")
    say(db, ai, "/quiz")
    say(db, ai, "bar")                      # a quiz answer
    assert db.query(ChatMessage).count() == 0 and ai.calls == []


def test_the_dashboard_chat_and_telegram_share_one_history(db):
    db.add(ChatMessage(role="user", content="dashboardda yozdim"))
    db.add(ChatMessage(role="assistant", content="ok"))
    db.commit()
    ai = Claude()
    say(db, ai, "Telegramda davom etaman")
    assert ai.calls[0]["history"][0]["content"] == "dashboardda yozdim"


# ── saved facts ───────────────────────────────────────────────────────

def test_remember_and_the_fact_reaches_every_new_chat(db):
    assert "Eslab qoldim" in say(db, Claude(), "/remember Men Python va Django o'rganyapman").text
    ai = Claude()
    say(db, ai, "Menga reja tuz")
    system = ai.calls[0]["system"]
    assert "Men Python va Django o'rganyapman" in system and "treat as true" in system
    assert "Bugun: " in system and study.local_today().isoformat() in system
    assert "never ask the owner to repeat" in system


def test_prompt_without_facts_has_no_empty_section(db):
    prompt = memory.system_prompt(db, "BASE")
    assert prompt.startswith("BASE") and "What the owner asked you to remember" not in prompt


def test_remember_in_plain_words(db):
    for text in ("eslab qol: ertalab 8 da turaman",
                 "Yodda tut, men backend o‘rganyapman",          # typographic apostrophe
                 "Eslab qol - men B2 darajadaman"):
        assert "Eslab qoldim" in say(db, Claude(), text).text, text
    assert [f.text for f in memory.list_facts(db)] == [
        "ertalab 8 da turaman", "men backend o'rganyapman", "men B2 darajadaman",
    ]
    # An ordinary sentence that merely contains the words is not a command.
    ai = Claude()
    say(db, ai, "eslab qolgan narsam yo'q")
    assert len(ai.calls) == 1 and len(memory.list_facts(db)) == 3


def test_remember_flow_and_one_message_form(db):
    r = say(db, Claude(), "/remember")
    assert "Nimani eslab qolay" in r.text and r.rows[0][0][1] == "do:/cancel"
    assert "Eslab qoldim: junior bo'lish" in say(db, Claude(), "junior bo'lish").text
    assert db.query(MemoryFact).count() == 1


def test_remember_rules(db, monkeypatch):
    assert memory.add_fact(db, "x")[0] is not None
    assert "allaqachon" in memory.add_fact(db, "X")[1]               # duplicate, any case
    assert "Juda uzun" in memory.add_fact(db, "a" * 400)[1]
    assert "yozing" in memory.add_fact(db, "   ")[1]
    monkeypatch.setattr(memory, "MAX_FACTS", 2)
    memory.add_fact(db, "ikkinchi")
    assert "to'ldi" in memory.add_fact(db, "uchinchi")[1]


def test_memory_screen_lists_and_deletes(db):
    r = say(db, Claude(), "/memory")
    assert "Hali hech narsa eslab qolinmagan" in r.text and r.rows[0][0][1] == "do:/remember"

    for t in ("birinchi", "ikkinchi"):
        memory.add_fact(db, t)
    r = say(db, Claude(), "/memory")
    assert "1. birinchi" in r.text and "2. ikkinchi" in r.text
    buttons = [d for row in r.rows for _, d in row]
    first_id = memory.list_facts(db)[0].id
    assert f"do:/forget {first_id}" in buttons and "do:/remember" in buttons

    assert "Unutdim" in say(db, Claude(), f"/forget {first_id}").text
    assert [f.text for f in memory.list_facts(db)] == ["ikkinchi"]
    assert "topilmadi" in say(db, Claude(), "/forget 999").text
    assert "Foydalanish" in say(db, Claude(), "/forget abc").text


# ── what the Claude CLI really receives ───────────────────────────────

def test_cli_provider_replays_the_history(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["prompt"] = kw["input"].decode()
        return SimpleNamespace(stdout=json.dumps({"result": "ok", "subtype": "success"}).encode(), stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"xabar {i} " + "z" * 900}
               for i in range(20)]
    ClaudeAgentProvider().chat("hozirgi savol", system="SYS", history=history)
    prompt = seen["prompt"]
    assert "Conversation so far:" in prompt and prompt.endswith("User: hozirgi savol")
    assert "xabar 19" in prompt and "xabar 4 " in prompt and "xabar 3 " not in prompt   # last 16 only
    assert max(len(line) for line in prompt.splitlines()) < 800                          # long ones cut
