import datetime as dt

from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.jobs import study_reminders as sr
from app.jobs import telegram_bot as tb
from app.models.study import PaperEntry, QuizSession, VocabCard
from app.study import service as study
from app.study.srs import schedule


def _sm():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)


class NoAI:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return "AI yo'q"


class FakeAI:
    """Returns questions for the question prompt and a grade for the grading prompt."""

    ai_available = True

    def chat(self, prompt, *, system=None, history=None):
        if system and "self-test questions" in system:
            return '[{"q": "Nima uchun list comprehension kerak?", "a": "qisqa va tez ro\'yxat yaratish"}]'
        if system and "grade" in system:
            return '{"score": 1, "feedback": "Aniq."}'
        return "ok"


class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append((url.rsplit("/", 1)[-1], json or {}))


# ── words + SM-2 ──────────────────────────────────────────────────────

def test_parse_and_add_words_dedupes():
    db = _sm()()
    text = "ephemeral - qisqa muddatli | An ephemeral joy\nwell-known = taniqli\nbad line"
    assert study.add_words(db, text) == (2, 0)
    assert study.add_words(db, "Ephemeral - boshqa") == (0, 1)  # same word, any case
    c = db.query(VocabCard).filter(VocabCard.word == "ephemeral").one()
    assert c.meaning == "qisqa muddatli" and c.example == "An ephemeral joy"


def test_sm2_progression_and_lapse():
    today = dt.date(2026, 1, 1)
    card = VocabCard(word="a", meaning="b", due_date=today)
    card.interval_days, card.ease, card.reps, card.lapses = 0, 2.5, 0, 0

    schedule(card, "good", today)
    assert (card.reps, card.interval_days, card.due_date) == (1, 1, today + dt.timedelta(days=1))
    schedule(card, "good", today)
    assert card.interval_days == 6
    schedule(card, "good", today)
    assert card.interval_days == round(6 * 2.5) or card.interval_days > 6   # grows by ease

    schedule(card, "again", today)
    assert card.reps == 0 and card.interval_days == 0 and card.lapses == 1
    assert card.due_date == today
    assert card.ease >= 1.3

    easy = VocabCard(word="x", meaning="y", due_date=today)
    easy.interval_days, easy.ease, easy.reps, easy.lapses = 0, 2.5, 0, 0
    schedule(easy, "easy", today)
    assert easy.ease > 2.5            # easy raises ease


def test_next_card_avoids_repeat_when_others_waiting():
    db = _sm()()
    today = study.local_today()
    study.add_words(db, "one - bir\ntwo - ikki", today)
    first = study.next_card(db, today)
    other = study.next_card(db, today, exclude_id=first.id)
    assert other.id != first.id
    # Only one card due: it may repeat.
    study.rate_card(db, other.id, "good", today)
    assert study.next_card(db, today, exclude_id=first.id).id == first.id


def test_words_command_and_stats():
    db = _sm()()
    assert "Hali so'z yo'q" in tb.handle_text(db, NoAI(), "/words")
    out = tb.handle_text(db, NoAI(), "/word\nabide - rioya qilmoq\nabandon - tashlab ketmoq")
    assert "Qo'shildi: 2" in out
    assert "Jami: 2" in tb.handle_text(db, NoAI(), "/words")
    assert "Foydalanish" in tb.handle_text(db, NoAI(), "/word")


# ── diary ─────────────────────────────────────────────────────────────

def test_diary_input_output_and_streak():
    db = _sm()()
    today = dt.date(2026, 3, 10)
    assert "hali yozilmagan" in study.diary_text(db, today=today)

    study.append_diary(db, "learned", "list comprehension", today)
    study.append_diary(db, "learned", "dict comprehension", today)   # appends
    out = study.diary_text(db, today=today)
    assert "list comprehension" in out and "dict comprehension" in out
    assert "Output yo'q" in out                      # nudge to write the output

    study.append_diary(db, "recalled", "comprehension - qisqa sikl", today)
    study.append_diary(db, "learned", "x", today - dt.timedelta(days=1))
    study.append_diary(db, "learned", "y", today - dt.timedelta(days=2))
    study.append_diary(db, "learned", "gap", today - dt.timedelta(days=4))  # breaks the streak
    assert study.diary_streak(db, today) == 3
    assert "Ketma-ket: 3" in study.diary_text(db, week=True, today=today)


def test_streak_survives_until_day_ends():
    db = _sm()()
    today = dt.date(2026, 3, 10)
    study.append_diary(db, "learned", "a", today - dt.timedelta(days=1))
    study.append_diary(db, "learned", "b", today - dt.timedelta(days=2))
    assert study.diary_streak(db, today) == 2        # today still empty, streak intact


def test_learned_and_recall_commands():
    db = _sm()()
    assert "Foydalanish" in tb.handle_text(db, NoAI(), "/learned")
    assert "input" in tb.handle_text(db, NoAI(), "/learned Django ORM").lower()
    assert "output" in tb.handle_text(db, NoAI(), "/recall ORM bu ma'lumotlar bazasi qatlami").lower()
    out = tb.handle_text(db, NoAI(), "/diary")
    assert "Django ORM" in out and "ORM bu" in out


# ── quiz ──────────────────────────────────────────────────────────────

def test_vocab_correct_is_lenient():
    assert study.vocab_correct("Qisqa muddatli", "qisqa muddatli")
    assert study.vocab_correct("rioya qilmok", "rioya qilmoq")             # one-letter typo
    assert not study.vocab_correct("rioya qilish", "rioya qilmoq")         # a different word form
    assert study.vocab_correct("tashlab", "tashlab ketmoq, voz kechmoq")   # one of several meanings
    assert not study.vocab_correct("", "x")
    assert not study.vocab_correct("mashina", "qisqa muddatli")


def test_quiz_flow_vocab_only_updates_schedule():
    db = _sm()()
    tb.handle_text(db, NoAI(), "/word\nabide - rioya qilmoq\nabandon - tashlab ketmoq")
    out = tb.handle_text(db, NoAI(), "/quiz")
    assert "2 ta savol" in out and "1/2" in out

    # Plain text is now an answer, not a chat message.
    first_q = db.query(QuizSession).one().questions[0]
    right = first_q["a"]
    out = tb.handle_text(db, NoAI(), right)
    assert "✅" in out and "2/2" in out
    out = tb.handle_text(db, NoAI(), "umuman boshqa narsa")
    assert "❌" in out and "Natija: 1/2" in out and "50%" in out
    assert study.active_quiz(db) is None

    # Quiz results feed spaced repetition: the missed word is due again today.
    wrong_card = db.get(VocabCard, db.query(QuizSession).one().questions[1]["card_id"])
    assert wrong_card.lapses == 1 and wrong_card.due_date <= study.local_today()


def test_quiz_with_ai_adds_recall_questions_and_grades():
    db = _sm()()
    study.append_diary(db, "learned", "list comprehension qisqa ro'yxat yaratadi")
    out = tb.handle_text(db, FakeAI(), "/quiz")
    assert "1/1" in out and "list comprehension" in out
    out = tb.handle_text(db, FakeAI(), "ro'yxatni tez yaratish uchun")
    assert "✅" in out and "Aniq." in out and "1/1" in out


def test_quiz_without_material_and_stop():
    db = _sm()()
    assert "material yo'q" in tb.handle_text(db, NoAI(), "/quiz")
    tb.handle_text(db, NoAI(), "/word a1 - bir")
    tb.handle_text(db, NoAI(), "/quiz")
    assert "to'xtatildi" in tb.handle_text(db, NoAI(), "/quiz stop")
    assert "Faol imtihon yo'q" in tb.handle_text(db, NoAI(), "/quiz stop")


def test_quiz_due_schedule():
    db = _sm()()
    today = study.local_today()
    assert study.quiz_due(db, 3, today) is False              # no material yet
    study.add_words(db, "a1 - bir", today)
    assert study.quiz_due(db, 3, today) is True               # never taken
    tb.handle_text(db, NoAI(), "/quiz")
    tb.handle_text(db, NoAI(), "bir")                         # finishes the 1-question quiz
    assert study.quiz_due(db, 3, today) is False
    assert study.quiz_due(db, 3, today + dt.timedelta(days=3)) is True


def test_drill_needs_ai():
    db = _sm()()
    assert "Claude ulangan" in tb.handle_text(db, NoAI(), "/drill python lists")

    class Mentor(NoAI):
        ai_available = True

        def chat(self, prompt, *, system=None, history=None):
            return "Vazifa: ro'yxatni teskari aylantiring."

    out = tb.handle_text(db, Mentor(), "/drill python lists")
    assert "teskari" in out and "AI va nusxa ko'chirishsiz" in out


# ── Telegram review buttons ───────────────────────────────────────────

def test_review_buttons_flow(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    sm = _sm()
    with sm() as db:
        study.add_words(db, "abide - rioya qilmoq\nabandon - tashlab ketmoq")
    http = Http()

    tb.process_update(http, sm, NoAI(), {"message": {"chat": {"id": 999}, "text": "/review"}})
    method, payload = http.calls[-1]
    assert method == "sendMessage" and "Navbatda: 2" in payload["text"]
    show = payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert show.startswith("rv:show:")
    card_id = int(show.split(":")[2])

    # Tap "show answer": the message is edited to the answer + 4 grading buttons.
    cb = {"id": "c1", "data": show, "message": {"message_id": 5, "chat": {"id": 999}}}
    tb.process_update(http, sm, NoAI(), {"callback_query": cb})
    edits = [c for c in http.calls if c[0] == "editMessageText"]
    assert "💡" in edits[-1][1]["text"]
    buttons = [b["callback_data"] for row in edits[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == [f"rv:rate:{card_id}:{g}" for g in ("again", "hard", "good", "easy")]

    # Tap "good": card is rescheduled and the next card is sent.
    n_before = len(http.calls)
    cb = {"id": "c2", "data": f"rv:rate:{card_id}:good", "message": {"message_id": 5, "chat": {"id": 999}}}
    tb.process_update(http, sm, NoAI(), {"callback_query": cb})
    with sm() as db:
        card = db.get(VocabCard, card_id)
        assert card.interval_days == 1 and card.reps == 1
    new_calls = http.calls[n_before:]
    assert any(c[0] == "sendMessage" and "Navbatda: 1" in c[1]["text"] for c in new_calls)


def test_callbacks_from_strangers_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    sm = _sm()
    with sm() as db:
        study.add_words(db, "abide - rioya qilmoq")
        cid = db.query(VocabCard).one().id
    http = Http()
    cb = {"id": "c", "data": f"rv:rate:{cid}:easy", "message": {"message_id": 1, "chat": {"id": 111}}}
    tb.process_update(http, sm, NoAI(), {"callback_query": cb})
    with sm() as db:
        assert db.get(VocabCard, cid).reps == 0      # untouched
    assert all(c[0] == "answerCallbackQuery" for c in http.calls)


def test_review_when_nothing_due(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    sm = _sm()
    http = Http()

    # No cards at all: say so and offer the button that fixes it.
    tb.process_update(http, sm, NoAI(), {"message": {"chat": {"id": 999}, "text": "/review"}})
    _, payload = http.calls[-1]
    assert "Hali so'z yo'q" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "do:/word"

    # Cards exist but none is due today: the session is finished.
    with sm() as db:
        study.add_words(db, "abide - rioya qilmoq")
        card = db.query(VocabCard).one()
        study.rate_card(db, card.id, "good")
    tb.process_update(http, sm, NoAI(), {"message": {"chat": {"id": 999}, "text": "/review"}})
    assert "tugadi" in http.calls[-1][1]["text"]


# ── reminders ─────────────────────────────────────────────────────────

def _configure(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "study_enabled", True)


def test_review_reminder_only_when_due(monkeypatch):
    _configure(monkeypatch)
    sm = _sm()
    http = Http()
    assert sr.remind_review(sm, http) is False and http.calls == []
    with sm() as db:
        study.add_words(db, "abide - rioya qilmoq")
    assert sr.remind_review(sm, http) is True
    _, payload = http.calls[-1]
    assert "1 ta so'z" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "rv:start"


def test_diary_reminder_asks_for_the_photo_until_the_day_is_done(monkeypatch):
    _configure(monkeypatch)
    sm = _sm()
    http = Http()
    assert sr.remind_diary(sm, http) is True
    text = http.calls[-1][1]["text"]
    assert "rasmga olib yuboring" in text
    assert http.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "do:/diary"

    with sm() as db:       # text fallback: input alone is not enough
        study.append_diary(db, "learned", "x")
    assert sr.remind_diary(sm, http) is True
    with sm() as db:
        study.append_diary(db, "recalled", "y")
    n = len(http.calls)
    assert sr.remind_diary(sm, http) is False and len(http.calls) == n   # text input + output

    # A confirmed paper entry also silences it; an unconfirmed one asks to confirm.
    sm2, http2 = _sm(), Http()
    with sm2() as db:
        db.add(PaperEntry(day=study.local_today(), confirmed=False))
        db.commit()
    assert sr.remind_diary(sm2, http2) is True and "tasdiqlanmagan" in http2.calls[-1][1]["text"]
    with sm2() as db:
        db.query(PaperEntry).one().confirmed = True
        db.commit()
    n = len(http2.calls)
    assert sr.remind_diary(sm2, http2) is False and len(http2.calls) == n


def test_quiz_reminder_and_disabled(monkeypatch):
    _configure(monkeypatch)
    sm = _sm()
    http = Http()
    assert sr.remind_quiz(sm, http) is False                  # nothing to test
    with sm() as db:
        study.add_words(db, "abide - rioya qilmoq")
    assert sr.remind_quiz(sm, http) is True and "/quiz" in http.calls[-1][1]["text"]
    monkeypatch.setattr(settings, "study_enabled", False)
    assert sr.remind_quiz(sm, Http()) is False


def test_reminders_noop_without_telegram(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    assert sr.remind_review(_sm(), Http()) is False
