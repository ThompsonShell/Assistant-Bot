import datetime as dt
import json
import os
import stat

import pytest

from app.bot import paper_flow, state
from app.config import settings
from app.db import Base, make_engine, make_sessionmaker
from app.jobs import study_reminders as sr
from app.jobs import telegram_bot as tb
from app.models.study import DiaryEntry, PaperEntry, VocabCard
from app.study import paper
from app.study import service as study

TODAY = study.local_today


def iso(days_ago=0):
    return (TODAY() - dt.timedelta(days=days_ago)).isoformat()


def page(**over):
    base = {
        "readable": True,
        "transcription": f"DATE: {iso()}\nTIME: Python 90 SQL 0 English 45 Algo 30 Other 0 | AI-off 120",
        "date": iso(),
        "minutes": {"python": 90, "sql": 0, "english": 45, "algo": 30, "other": 0},
        "ai_off": 120,
        "learned": "list comprehension",
        "output": "wrote a Stack class",
        "mistakes": "forgot self",
        "words": "abide - rioya qilmoq\nabandon - tashlab ketmoq",
        "question": "what is __slots__?",
        "tomorrow": "OOP part 2",
    }
    base.update(over)
    return base


class Vision:
    ai_available = True

    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload if payload is not None else page(), error, []

    def vision(self, prompt, image_path, *, system=None):
        self.calls.append((prompt, image_path, system))
        if self.error:
            raise self.error
        return json.dumps(self.payload, default=str)

    def chat(self, prompt, *, system=None, history=None):
        return f"ECHO: {prompt}"


class NoVision:
    ai_available = False

    def chat(self, prompt, *, system=None, history=None):
        return f"ECHO: {prompt}"


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diary_photo_dir", str(tmp_path / "photos"))
    monkeypatch.setattr(settings, "diary_backfill_hours", 48)
    return tmp_path / "photos"


@pytest.fixture
def db():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)()


def send(db, provider, caption="", data=b"fake-jpeg"):
    return paper_flow.handle_photo(db, provider, data, caption)


def cb(reply):
    return [d for row in reply.rows for _, d in row]


def say(db, text, provider=None):
    return tb.handle_message(db, provider or Vision(), text)


# ── parsing and dates ─────────────────────────────────────────────────

def test_parse_page_validates_numbers_and_date():
    ok = paper.parse_page(json.dumps(page()))
    assert ok["date"] == TODAY() and ok["minutes"]["python"] == 90 and ok["ai_off"] == 120

    bad = paper.parse_page(json.dumps(page(minutes={"python": -5, "sql": "abc", "english": 30}, date="not a date")))
    assert bad["minutes"]["python"] is None and bad["minutes"]["sql"] is None   # never guessed
    assert bad["minutes"]["english"] == 30 and bad["date"] is None

    over = paper.parse_page(json.dumps(page(minutes={"python": 900, "sql": 900})))   # more than a day
    assert all(v is None for v in over["minutes"].values())

    assert paper.parse_page("sorry I cannot") is None
    fenced = paper.parse_page("```json\n" + json.dumps(page()) + "\n```")
    assert fenced is not None


def test_caption_date_and_backfill_window():
    assert paper.caption_date("Bugun date: 2026-11-18 edi") == dt.date(2026, 11, 18)
    assert paper.caption_date("DATE:2026-01-02") == dt.date(2026, 1, 2)
    assert paper.caption_date("no date here") is None

    t = TODAY()
    assert paper.backfill_error(t, t) is None
    assert paper.backfill_error(t - dt.timedelta(days=2), t) is None            # 48 h ok
    assert "juda eski" in paper.backfill_error(t - dt.timedelta(days=3), t)
    assert "kelajak" in paper.backfill_error(t + dt.timedelta(days=1), t)


# ── a photo becomes a summary, nothing counts yet ─────────────────────

def test_complete_page_shows_summary_with_four_buttons(db, photo_dir):
    r = send(db, Vision())
    assert f"Qog'oz kundalik — {iso()}" in r.text and "(rasmdan o'qildi)" in r.text
    assert "Python 90" in r.text and "AI-off: 120" in r.text and "Jami: 2 s 45 d" in r.text
    assert "list comprehension" in r.text and "OOP part 2" in r.text
    assert "So'zlar: abide - rioya qilmoq · abandon - tashlab ketmoq" in r.text   # lines stay apart
    assert "statistikaga qo'shilmaydi" in r.text

    entry = db.query(PaperEntry).one()
    assert cb(r) == [f"pe:ok:{entry.id}", f"pe:edit:{entry.id}", f"pe:date:{entry.id}", f"pe:retake:{entry.id}"]
    assert entry.confirmed is False
    assert db.query(DiaryEntry).count() == 0                   # not fanned out yet

    photo = entry.photo_paths[0]
    assert os.path.dirname(photo) == str(photo_dir)
    assert stat.S_IMODE(os.stat(photo).st_mode) == 0o600        # private file
    assert state.get_state(db) is None


def test_vision_is_told_never_to_invent_text(db):
    v = Vision()
    send(db, v)
    prompt, path, system = v.calls[0]
    assert "NEVER correct" in system and "null" in system and "[?]" in system
    assert "DATE" in system and "WROTE MYSELF" in system        # knows the paper template


# ── missing numbers are asked, never guessed ──────────────────────────

def test_missing_minutes_are_asked_one_by_one(db):
    p = page(minutes={"python": 90, "sql": None, "english": None, "algo": 30, "other": None}, ai_off=None)
    r = send(db, Vision(p))
    assert "SQL necha daqiqa?" in r.text and "Sahifa o'qildi" in r.text
    assert state.get_state(db)[0] == "paper:min"
    entry_id = db.query(PaperEntry).one().id
    assert cb(r) == [f"pe:z:{entry_id}:sql", f"pe:skip:{entry_id}"]

    assert "Daqiqani raqam" in say(db, "ko'p").text              # unusable -> same question stays
    assert state.get_state(db)[1]["key"] == "sql"

    r = say(db, "60 min")
    assert "English necha daqiqa?" in r.text
    r = tb.handle_message(db, Vision(), "yo'q")                  # "none" means 0
    assert "Other necha daqiqa?" in r.text
    r = say(db, "0")
    assert "AI'siz" in r.text
    r = say(db, "100")
    assert "Qog'oz kundalik" in r.text and "Python 90 · SQL 60 · English 0 · Algo 30 · Other 0 | AI-off: 100" in r.text
    assert state.get_state(db) is None


def test_zero_button_and_skip_button(db):
    p = page(minutes={"python": 90, "sql": None, "english": None, "algo": None, "other": None}, ai_off=None)
    send(db, Vision(p))
    entry = db.query(PaperEntry).one()
    r = paper_flow.on_callback(db, ["pe", "z", str(entry.id), "sql"])
    assert "English necha daqiqa?" in r.text and db.get(PaperEntry, entry.id).minutes["sql"] == 0
    r = paper_flow.on_callback(db, ["pe", "skip", str(entry.id)])
    assert "Qog'oz kundalik" in r.text and state.get_state(db) is None
    assert db.get(PaperEntry, entry.id).minutes["english"] is None      # left blank, not invented


# ── date rules ────────────────────────────────────────────────────────

def test_caption_date_wins_and_old_dates_are_refused(db, photo_dir):
    r = send(db, Vision(), caption=f"date: {iso(1)}")
    assert iso(1) in r.text and "(izohdan)" in r.text

    r = send(db, Vision(), caption=f"date: {iso(5)}")
    assert "juda eski" in r.text and "Boshqa sana" in r.text
    assert db.query(PaperEntry).count() == 1 and len(os.listdir(photo_dir)) == 1   # nothing stored

    r = send(db, Vision(), caption=f"date: {(TODAY() + dt.timedelta(days=1)).isoformat()}")
    assert "kelajak" in r.text


def test_date_command_applies_to_the_next_photo_only(db):
    assert "keyingi rasm" in say(db, "/date").text.lower()
    assert "Keyingi rasm" in say(db, iso(2)).text and state.get_state(db) is None
    r = send(db, Vision())
    assert iso(2) in r.text and "(/date)" in r.text
    r = send(db, Vision(page(date=iso(0))))
    assert "(rasmdan o'qildi)" in r.text                         # used up

    assert "juda eski" in say(db, f"/date {iso(9)}").text
    assert "2026-11-20 shaklida" in say(db, "/date kecha").text


def test_page_date_outside_the_window_falls_back_to_today(db):
    r = send(db, Vision(page(date=iso(30))))
    assert f"rasmdagi sana {iso(30)} mos kelmadi, bugun deb olindi" in r.text
    assert db.query(PaperEntry).one().day == TODAY()


def test_page_without_date_uses_today_and_says_so(db):
    r = send(db, Vision(page(date=None)))
    assert "rasmda sana yo'q, bugun deb olindi" in r.text


def test_wrong_date_button_moves_the_entry(db):
    send(db, Vision())
    entry = db.query(PaperEntry).one()
    r = paper_flow.on_callback(db, ["pe", "date", str(entry.id)])
    assert "qaysi kunga" in r.text and state.get_state(db)[0] == "paper:date"

    assert "shaklida" in say(db, "kecha").text                   # not a date: asked again
    assert "juda eski" in say(db, iso(10)).text                  # outside window: asked again
    r = say(db, iso(1))
    assert iso(1) in r.text and "(sana o'zgartirildi)" in r.text
    assert db.get(PaperEntry, entry.id).day == TODAY() - dt.timedelta(days=1)


def test_wrong_date_cannot_collide_with_another_entry(db):
    send(db, Vision(), caption=f"date: {iso(1)}")
    send(db, Vision())                                           # today
    today_entry = db.query(PaperEntry).filter(PaperEntry.day == TODAY()).one()
    paper_flow.on_callback(db, ["pe", "date", str(today_entry.id)])
    assert "allaqachon bor" in say(db, iso(1)).text


# ── unreadable, no vision, errors ─────────────────────────────────────

def test_unreadable_page_asks_for_a_retake_and_keeps_nothing(db, photo_dir):
    r = send(db, Vision(page(readable=False, transcription="", learned="", output="", mistakes="",
                              words="", question="", tomorrow="")))
    assert "o'qib bo'lmadi" in r.text and "qayta suratga" in r.text
    assert db.query(PaperEntry).count() == 0
    assert not photo_dir.exists() or os.listdir(photo_dir) == []


@pytest.mark.parametrize("provider,fragment", [
    (NoVision(), "Claude ulangan bo'lishi kerak"),
    (Vision(error=RuntimeError("claude failed")), "Rasmni o'qishda xato"),
])
def test_when_reading_fails_the_photo_is_kept_and_numbers_are_typed(db, provider, fragment):
    r = send(db, provider)
    assert fragment in r.text and "qo'lda kiriting" in r.text
    assert "Python necha daqiqa?" in r.text                      # falls back to typing the numbers
    entry = db.query(PaperEntry).one()
    assert entry.photo_paths and entry.transcription == ""


def test_unusable_model_answer_is_reported(db):
    class Bad(Vision):
        def vision(self, *a, **k):
            return "I can't help with that"

    r = send(db, Bad())
    assert "Javobni tushunib bo'lmadi" in r.text


# ── a second photo, editing, retake ───────────────────────────────────

def test_second_photo_for_the_same_day_appends(db):
    send(db, Vision())
    entry = db.query(PaperEntry).one()
    paper.confirm(db, entry)
    assert entry.confirmed

    p2 = page(transcription="page two", learned="dict comprehension",
              minutes={"python": 999 // 10, "sql": 5, "english": 5, "algo": 5, "other": 5}, ai_off=5)
    r = send(db, Vision(p2))
    entry = db.query(PaperEntry).one()
    assert db.query(PaperEntry).count() == 1 and len(entry.photo_paths) == 2
    assert "page two" in entry.transcription and "---" in entry.transcription
    assert entry.parsed["learned"] == "list comprehension\ndict comprehension"
    assert entry.minutes["python"] == 90 and entry.ai_off_minutes == 120   # no double counting
    assert entry.confirmed is False                                         # confirm again
    assert "Rasmlar: 2" in r.text


def test_edit_a_number_and_a_text_field(db):
    send(db, Vision())
    e = db.query(PaperEntry).one()

    picker = paper_flow.on_callback(db, ["pe", "edit", str(e.id)])
    assert f"pe:f:{e.id}:python" in cb(picker) and f"pe:f:{e.id}:aioff" in cb(picker)
    assert f"pe:f:{e.id}:mistakes" in cb(picker) and f"pe:sum:{e.id}" in cb(picker)

    assert "Python necha daqiqa?" in paper_flow.on_callback(db, ["pe", "f", str(e.id), "python"]).text
    assert "Python 120" in say(db, "120").text
    assert "Xatolar" in paper_flow.on_callback(db, ["pe", "f", str(e.id), "mistakes"]).text
    assert "Xatolar: off by one" in say(db, "off by one").text
    assert state.get_state(db) is None


def test_retake_discards_an_unconfirmed_entry_and_its_photo(db, photo_dir):
    send(db, Vision())
    e = db.query(PaperEntry).one()
    r = paper_flow.on_callback(db, ["pe", "retake", str(e.id)])
    assert "Yangi rasmni yuboring" in r.text
    assert db.query(PaperEntry).count() == 0 and os.listdir(photo_dir) == []

    send(db, Vision())
    e = db.query(PaperEntry).one()
    paper.confirm(db, e)
    assert "tasdiqlangan" in paper_flow.on_callback(db, ["pe", "retake", str(e.id)]).text
    assert db.query(PaperEntry).count() == 1                     # a confirmed entry is never dropped by a tap


# ── confirm ───────────────────────────────────────────────────────────

def test_confirm_feeds_the_diary_and_proposes_words(db):
    send(db, Vision())
    e = db.query(PaperEntry).one()
    r = paper_flow.on_callback(db, ["pe", "ok", str(e.id)])
    assert f"Saqlandi: {iso()}" in r.text and "2 s 45 d" in r.text and "Ketma-ket: 1 kun" in r.text
    assert "abide — rioya qilmoq" in r.text and cb(r) == [f"pe:addw:{e.id}"]

    db.refresh(e)
    assert e.confirmed and e.confirmed_at is not None
    diary = db.query(DiaryEntry).one()
    assert diary.learned == "list comprehension" and diary.recalled == "wrote a Stack class"
    assert db.query(VocabCard).count() == 0                      # words are only proposed

    assert "2 ta so'z" in paper_flow.on_callback(db, ["pe", "addw", str(e.id)]).text
    assert db.query(VocabCard).count() == 2
    assert "allaqachon bor" in paper_flow.on_callback(db, ["pe", "addw", str(e.id)]).text


def test_confirm_lists_words_without_a_meaning(db):
    send(db, Vision(page(words="abide - rioya qilmoq\nabandon, abate")))
    e = db.query(PaperEntry).one()
    r = paper_flow.on_callback(db, ["pe", "ok", str(e.id)])
    assert "Ma'nosi yozilmagan: abandon, abate" in r.text


def test_checklist_follows_the_photo_status(db):
    from app.bot import views

    assert views.paper_status(db, TODAY()) == "none"
    send(db, Vision())
    assert views.paper_status(db, TODAY()) == "pending" and "(tasdiqlanmagan)" in say(db, "/diary").text
    paper.confirm(db, db.query(PaperEntry).one())
    assert views.paper_status(db, TODAY()) == "confirmed" and "✅ 📷" in say(db, "/diary").text
    out = say(db, "/diary")
    assert "✅ 📥" in out.text and "✅ 📤" in out.text            # input/output came from the page


# ── /delete_entry ─────────────────────────────────────────────────────

def test_delete_entry_needs_confirmation_and_removes_the_photo(db, photo_dir):
    send(db, Vision())
    e = db.query(PaperEntry).one()
    r = say(db, f"/delete_entry {iso()}")
    assert "o'chirilsinmi" in r.text and cb(r) == [f"pe:del:{e.id}", "do:/menu"]
    assert db.query(PaperEntry).count() == 1 and os.listdir(photo_dir)      # nothing happened yet

    assert "o'chirildi" in paper_flow.on_callback(db, ["pe", "del", str(e.id)]).text
    assert db.query(PaperEntry).count() == 0 and os.listdir(photo_dir) == []


def test_delete_entry_asks_for_the_date_and_handles_missing(db):
    assert "Qaysi kunning" in say(db, "/delete_entry").text
    assert "yozuv yo'q" in say(db, iso(1)).text
    assert "shaklida" in say(db, "/delete_entry kecha").text


# ── through process_update (real Telegram shapes) ─────────────────────

class Resp:
    def __init__(self, payload=None, content=b""):
        self._p, self.content = payload, content

    def json(self):
        return self._p


class Http:
    def __init__(self, size=100):
        self.posts, self.gets, self.size = [], [], size

    def post(self, url, json=None, **kw):
        self.posts.append((url.rsplit("/", 1)[-1], json or {}))

    def get(self, url, params=None, **kw):
        self.gets.append(url)
        if url.endswith("/getFile"):
            return Resp({"ok": True, "result": {"file_path": "photos/f1.jpg", "file_size": self.size}})
        return Resp(content=b"jpeg-bytes")


def photo_update(chat=999, caption=None, key="message"):
    msg = {"chat": {"id": chat}, "photo": [
        {"file_id": "small", "width": 90, "height": 90, "file_size": 1000},
        {"file_id": "big", "width": 1280, "height": 960, "file_size": 90000},
    ]}
    if caption:
        msg["caption"] = caption
    return {key: msg}


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "telegram_bot_token", "TOKEN")


def test_photo_message_is_downloaded_read_and_answered(owner):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm, http, vision = make_sessionmaker(engine), Http(), Vision()

    tb.process_update(http, sm, vision, photo_update())
    texts = [p[1] for p in http.posts if p[0] == "sendMessage"]
    assert "qabul qilindi" in texts[0]["text"]
    assert "Qog'oz kundalik" in texts[1]["text"]
    assert texts[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("pe:ok:")
    assert any(u.endswith("/getFile") for u in http.gets)
    assert any("file/botTOKEN/photos/f1.jpg" in u for u in http.gets)
    with sm() as db:
        assert db.query(PaperEntry).count() == 1


def test_largest_photo_size_and_image_documents_are_used():
    msg = photo_update()["message"]
    assert tb._photo_of(msg) == ("big", ".jpg")
    assert tb._photo_of({"document": {"file_id": "d1", "mime_type": "image/png"}}) == ("d1", ".png")
    assert tb._photo_of({"document": {"file_id": "d2", "mime_type": "application/pdf"}}) is None
    assert tb._photo_of({"text": "hi"}) is None


def test_caption_reaches_the_date_rules(owner):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm, http = make_sessionmaker(engine), Http()
    tb.process_update(http, sm, Vision(), photo_update(caption=f"date: {iso(1)}"))
    with sm() as db:
        assert db.query(PaperEntry).one().day == TODAY() - dt.timedelta(days=1)


def test_strangers_and_edits_and_big_files_are_ignored(owner):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = make_sessionmaker(engine)

    http = Http()
    tb.process_update(http, sm, Vision(), photo_update(chat=111))
    assert http.gets == []                                        # never downloaded
    assert "faqat egasi" in http.posts[0][1]["text"]

    http = Http()
    tb.process_update(http, sm, Vision(), photo_update(key="edited_message"))
    assert http.posts == [] and http.gets == []

    http = Http(size=50_000_000)
    tb.process_update(http, sm, Vision(), photo_update())
    assert "10 MB" in http.posts[-1][1]["text"]
    with sm() as db:
        assert db.query(PaperEntry).count() == 0


def test_confirm_button_through_telegram(owner):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm, http = make_sessionmaker(engine), Http()
    tb.process_update(http, sm, Vision(), photo_update())
    with sm() as db:
        eid = db.query(PaperEntry).one().id

    update = {"callback_query": {"id": "c", "data": f"pe:ok:{eid}",
                                 "message": {"message_id": 7, "chat": {"id": 999}}}}
    n = len(http.posts)
    tb.process_update(http, sm, Vision(), update)
    new = http.posts[n:]
    assert any(m == "editMessageReplyMarkup" and p["reply_markup"] == {"inline_keyboard": []} for m, p in new)
    assert any(m == "sendMessage" and "Saqlandi" in p["text"] for m, p in new)
    with sm() as db:
        assert db.get(PaperEntry, eid).confirmed

    stranger = {"callback_query": {"id": "c", "data": f"pe:del:{eid}",
                                   "message": {"message_id": 7, "chat": {"id": 111}}}}
    tb.process_update(http, sm, Vision(), stranger)
    with sm() as db:
        assert db.get(PaperEntry, eid) is not None               # untouched


# ── next-morning reminder ─────────────────────────────────────────────

def test_unconfirmed_entries_are_asked_about_once_the_next_morning(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "study_enabled", True)

    class Sm:                                                     # session_local() stand-in
        def __call__(self):
            return _Ctx(db)

    class _Ctx:
        def __init__(self, d): self.d = d
        def __enter__(self): return self.d
        def __exit__(self, *a): return False

    class H:
        def __init__(self): self.sent = []
        def post(self, url, json=None, **kw): self.sent.append(json)

    send(db, Vision(), caption=f"date: {iso(1)}")                 # yesterday, unconfirmed
    send(db, Vision())                                            # today: not old enough yet
    h = H()
    assert sr.remind_unconfirmed(Sm(), h) == 1
    assert "Tasdiqlanmagan kundalik" in h.sent[0]["text"] and iso(1) in h.sent[0]["text"]
    assert h.sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("pe:ok:")

    h2 = H()
    assert sr.remind_unconfirmed(Sm(), h2) == 0 and h2.sent == []  # asked only once
