"""Self-study features behind the bot's /word, /review, /learned, /recall,
/diary, /quiz and /drill commands.

Everything here works on a database session and returns plain text, so the
Telegram layer only has to send it. Vocabulary quizzes are graded locally;
diary ("recall") questions use the AI provider when it is connected.
"""
from __future__ import annotations

import datetime as dt
import re
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from ..config import settings
from ..models.study import DiaryEntry, QuizSession, ReadingLog, VocabCard
from ..providers.base import extract_json
from .srs import GRADES, schedule


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.display_timezone)
    except Exception:  # noqa: BLE001 - unknown tz falls back to UTC
        return ZoneInfo("UTC")


def local_today() -> dt.date:
    """Today's date in the display timezone."""
    return dt.datetime.now(_tz()).date()


# ── Vocabulary ────────────────────────────────────────────────────────

_SPLIT_RE = re.compile(r"\s+[-–—]\s+|\s*=\s*|\s*:\s+")


def parse_words(text: str) -> list[tuple[str, str, str | None]]:
    """Parse lines like ``ephemeral - qisqa muddatli | An ephemeral joy``.

    Returns (word, meaning, example) tuples; lines without a separator are
    ignored. The example after ``|`` is optional.
    """
    out: list[tuple[str, str, str | None]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _SPLIT_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            continue
        word, rest = parts[0].strip(), parts[1].strip()
        example = None
        if "|" in rest:
            rest, example = (x.strip() for x in rest.split("|", 1))
        if word and rest:
            out.append((word[:200], rest[:500], (example or None) and example[:500]))
    return out


def add_words(db, text: str, today: dt.date | None = None) -> tuple[int, int]:
    """Add cards from text. Returns (added, already_existing)."""
    today = today or local_today()
    added = skipped = 0
    for word, meaning, example in parse_words(text):
        exists = (
            db.query(VocabCard)
            .filter(VocabCard.word.ilike(word))
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(VocabCard(word=word, meaning=meaning, example=example, due_date=today))
        added += 1
    db.commit()
    return added, skipped


def due_cards(db, today: dt.date) -> list[VocabCard]:
    return (
        db.query(VocabCard)
        .filter(VocabCard.due_date <= today)
        .order_by(VocabCard.due_date, VocabCard.last_reviewed.is_not(None), VocabCard.id)
        .all()
    )


def next_card(db, today: dt.date, exclude_id: int | None = None) -> VocabCard | None:
    """The next card to review. Avoids repeating the one just seen when other
    cards are waiting."""
    cards = due_cards(db, today)
    for c in cards:
        if c.id != exclude_id:
            return c
    return cards[0] if cards else None


def rate_card(db, card_id: int, grade: str, today: dt.date | None = None) -> VocabCard | None:
    """Apply a self-grade (again/hard/good/easy) to a card."""
    if grade not in GRADES:
        return None
    card = db.get(VocabCard, card_id)
    if card is None:
        return None
    schedule(card, grade, today or local_today())
    db.commit()
    return card


def vocab_stats(db, today: dt.date | None = None) -> dict[str, int]:
    today = today or local_today()
    total = db.query(VocabCard).count()
    return {
        "total": total,
        "due": len(due_cards(db, today)),
        "learned": db.query(VocabCard).filter(VocabCard.interval_days >= 21).count(),
    }


def card_front(card: VocabCard) -> str:
    return f"🃏 {card.word}\n\nMa'nosini eslang, so'ng javobni ko'ring."


def card_back(card: VocabCard) -> str:
    text = f"🃏 {card.word}\n\n💡 {card.meaning}"
    if card.example:
        text += f"\n\n📖 {card.example}"
    return text + "\n\nQanchalik esladingiz?"


def words_text(db) -> str:
    s = vocab_stats(db)
    if not s["total"]:
        return (
            "📚 Hali so'z yo'q.\n\nQo'shish:\n/word ephemeral - qisqa muddatli\n"
            "Bir nechta so'zni har birini yangi qatorga yozing."
        )
    return (
        f"📚 Jami: {s['total']} ta so'z\n"
        f"🔁 Bugun takrorlash: {s['due']}\n"
        f"🏆 Mustahkamlangan (21+ kun oraliq): {s['learned']}\n\n"
        "/review — takrorlashni boshlash"
    )


# ── Diary (input / output) ────────────────────────────────────────────

_FIELD_LABEL = {"learned": "📥 O'rgandim (input)", "recalled": "📤 Yodimdan (output)"}


def append_diary(db, field: str, text: str, day: dt.date | None = None) -> DiaryEntry:
    """Append text to today's entry. ``field`` is "learned" or "recalled"."""
    day = day or local_today()
    entry = db.query(DiaryEntry).filter(DiaryEntry.day == day).first()
    if entry is None:
        entry = DiaryEntry(day=day, learned="", recalled="")
        db.add(entry)
    current = getattr(entry, field) or ""
    setattr(entry, field, (current + "\n" + text).strip() if current else text.strip())
    db.commit()
    return entry


def _filled(e: DiaryEntry) -> bool:
    return bool((e.learned or "").strip() or (e.recalled or "").strip())


def diary_streak(db, today: dt.date | None = None) -> int:
    """Consecutive days with an entry, ending today (or yesterday if today is
    still empty, so the streak isn't lost before the day is over)."""
    today = today or local_today()
    days = {e.day for e in db.query(DiaryEntry).all() if _filled(e)}
    cursor = today if today in days else today - dt.timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def diary_text(db, week: bool = False, today: dt.date | None = None) -> str:
    today = today or local_today()
    if week:
        lines = ["📓 So'nggi 7 kun:"]
        entries = {e.day: e for e in db.query(DiaryEntry).all()}
        for i in range(6, -1, -1):
            d = today - dt.timedelta(days=i)
            e = entries.get(d)
            mark = "✅" if e is not None and _filled(e) else "▫️"
            both = "" if e is None else (" · input+output" if (e.learned and e.recalled) else "")
            lines.append(f"{mark} {d.strftime('%a %d-%b')}{both}")
        lines.append(f"\n🔥 Ketma-ket: {diary_streak(db, today)} kun")
        return "\n".join(lines)

    e = db.query(DiaryEntry).filter(DiaryEntry.day == today).first()
    head = f"📓 Bugun ({today.strftime('%d-%b')}) · 🔥 {diary_streak(db, today)} kun ketma-ket"
    if e is None or not _filled(e):
        return (
            head + "\n\nBugun hali yozilmagan.\n\n"
            "/learned bugun nimani o'rgandingiz\n"
            "/recall kitobga qaramasdan o'zingiz tushuntirib yozing"
        )
    parts = [head]
    for field in ("learned", "recalled"):
        value = (getattr(e, field) or "").strip()
        parts.append(f"\n{_FIELD_LABEL[field]}:\n{value if value else '— yozilmagan'}")
    if not (e.recalled or "").strip():
        parts.append("\n💡 Output yo'q: o'rgangan narsangizni qaramasdan /recall bilan yozing.")
    return "\n".join(parts)


# ── Quiz ──────────────────────────────────────────────────────────────

QUESTION_SYSTEM = (
    "You write short self-test questions from a learner's study notes. "
    "Reply with ONLY a JSON array: [{\"q\": str, \"a\": str}]. Each question must "
    "be answerable in one or two sentences, test understanding (not trivia), and "
    "be written in the same language as the notes. \"a\" is the short expected answer."
)

GRADE_SYSTEM = (
    "You grade a learner's short answer against the expected answer. Be fair: "
    "accept different wording if the idea is right. Reply with ONLY JSON: "
    "{\"score\": 0 | 0.5 | 1, \"feedback\": \"<one short sentence in Uzbek>\"}."
)


def _norm(s: str) -> str:
    s = (s or "").lower()
    for ch in "’‘ʻʼ`´":
        s = s.replace(ch, "'")
    s = re.sub(r"[^\w\s']", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def vocab_correct(answer: str, expected: str) -> bool:
    """Lenient local check: exact, close spelling, or one of several meanings."""
    a = _norm(answer)
    if not a:
        return False
    options = [_norm(x) for x in re.split(r"[,;/]|\byoki\b", expected) if x.strip()]
    options.append(_norm(expected))
    for o in options:
        if not o:
            continue
        if a == o or SequenceMatcher(None, a, o).ratio() >= 0.8:
            return True
        if len(o) >= 4 and o in a:
            return True
        if len(a) >= 4 and a in o:
            return True
    return False


def _ai_questions(provider, notes: str, n: int) -> list[dict[str, str]]:
    if not n or not notes.strip() or not getattr(provider, "ai_available", False):
        return []
    try:
        raw = provider.chat(
            f"Notes:\n{notes[:4000]}\n\nWrite {n} questions.", system=QUESTION_SYSTEM
        )
    except Exception:  # noqa: BLE001
        return []
    data = extract_json(raw or "")
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("q") and item.get("a"):
            out.append({"q": str(item["q"])[:300], "a": str(item["a"])[:400]})
    return out[:n]


def build_quiz(db, provider, today: dt.date | None = None,
               n_vocab: int = 5, n_recall: int = 3) -> list[dict[str, Any]]:
    """Mix vocabulary questions (weakest/due first) with questions from the
    last three days of diary notes (AI only)."""
    today = today or local_today()
    cards = (
        db.query(VocabCard)
        .order_by(VocabCard.due_date, VocabCard.ease, VocabCard.id)
        .limit(n_vocab)
        .all()
    )
    questions: list[dict[str, Any]] = [
        {"kind": "vocab", "q": f"«{c.word}» — ma'nosi nima?", "a": c.meaning, "card_id": c.id}
        for c in cards
    ]
    since = today - dt.timedelta(days=2)
    notes = "\n".join(
        f"{e.learned}\n{e.recalled}"
        for e in db.query(DiaryEntry).filter(DiaryEntry.day >= since).all()
    )
    for item in _ai_questions(provider, notes, n_recall):
        questions.append({"kind": "recall", "q": item["q"], "a": item["a"], "card_id": None})
    return questions


def active_quiz(db) -> QuizSession | None:
    return (
        db.query(QuizSession)
        .filter(QuizSession.finished.is_(False))
        .order_by(QuizSession.id.desc())
        .first()
    )


def _ask(session: QuizSession) -> str:
    total = len(session.questions)
    q = session.questions[session.index]
    return f"🧪 {session.index + 1}/{total} — {q['q']}"


def start_quiz(db, provider, today: dt.date | None = None) -> str:
    old = active_quiz(db)
    if old is not None:
        old.finished = True
    questions = build_quiz(db, provider, today)
    if not questions:
        db.commit()
        return (
            "🧪 Imtihon uchun material yo'q.\n\n"
            "So'z qo'shing: /word ephemeral - qisqa muddatli\n"
            "Yoki kundalik yozing: /learned ..."
        )
    session = QuizSession(questions=questions, index=0, correct=0.0, finished=False)
    db.add(session)
    db.commit()
    return (
        f"🧪 Imtihon boshlandi: {len(questions)} ta savol.\n"
        "Javoblarni oddiy matn qilib yozing. To'xtatish: /quiz stop\n\n" + _ask(session)
    )


def stop_quiz(db) -> str:
    session = active_quiz(db)
    if session is None:
        return "Faol imtihon yo'q."
    session.finished = True
    db.commit()
    return "🛑 Imtihon to'xtatildi."


def _grade_recall(provider, q: str, expected: str, answer: str) -> tuple[float, str]:
    if getattr(provider, "ai_available", False):
        try:
            raw = provider.chat(
                f"Question: {q}\nExpected: {expected}\nLearner's answer: {answer}",
                system=GRADE_SYSTEM,
            )
            data = extract_json(raw or "")
            if isinstance(data, dict) and "score" in data:
                score = float(data["score"])
                score = 1.0 if score >= 0.75 else 0.5 if score >= 0.25 else 0.0
                return score, str(data.get("feedback", ""))[:200]
        except Exception:  # noqa: BLE001
            pass
    # Fallback: share of the expected answer's key words that appear in the reply.
    exp = {w for w in _norm(expected).split() if len(w) >= 4}
    if not exp:
        return 0.0, ""
    share = len(exp & set(_norm(answer).split())) / len(exp)
    return (1.0 if share >= 0.6 else 0.5 if share >= 0.3 else 0.0), ""


def answer_quiz(db, provider, text: str, today: dt.date | None = None) -> str:
    """Grade the owner's reply to the current question and ask the next one."""
    today = today or local_today()
    session = active_quiz(db)
    if session is None:
        return "Faol imtihon yo'q. /quiz bilan boshlang."

    questions = [dict(q) for q in session.questions]
    cur = questions[session.index]
    if cur["kind"] == "vocab":
        score = 1.0 if vocab_correct(text, cur["a"]) else 0.0
        feedback = "✅ To'g'ri!" if score else f"❌ To'g'ri javob: {cur['a']}"
        if cur.get("card_id"):  # quiz results feed the review schedule
            rate_card(db, cur["card_id"], "good" if score else "again", today)
    else:
        score, note = _grade_recall(provider, cur["q"], cur["a"], text)
        head = "✅ To'g'ri!" if score == 1 else "🟡 Qisman to'g'ri." if score else "❌ Noto'g'ri."
        feedback = head + (f" {note}" if note else "") + ("" if score == 1 else f"\n💡 Javob: {cur['a']}")

    cur["ok"], cur["given"] = score, text[:300]
    questions[session.index] = cur
    session.questions = questions
    session.correct = (session.correct or 0.0) + score
    session.index += 1

    if session.index >= len(questions):
        session.finished = True
        db.commit()
        total = len(questions)
        pct = round(100 * session.correct / total)
        lines = [feedback, "", f"🏁 Natija: {session.correct:g}/{total} ({pct}%)"]
        missed = [q for q in questions if q.get("ok", 0) < 1]
        if missed:
            lines.append("\nQayta ko'ring:")
            lines += [f"• {q['q']} → {q['a']}" for q in missed[:5]]
        lines.append("\n" + ("👏 Zo'r!" if pct >= 80 else "💪 Yaxshi, takrorlashda davom eting." if pct >= 50 else "📚 Ko'proq takrorlash kerak: /review"))
        return "\n".join(lines)

    db.commit()
    return feedback + "\n\n" + _ask(session)


def last_quiz_day(db) -> dt.date | None:
    last = (
        db.query(QuizSession)
        .filter(QuizSession.finished.is_(True))
        .order_by(QuizSession.id.desc())
        .first()
    )
    if last is None:
        return None
    ts = last.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(_tz()).date()


def quiz_due(db, every_days: int, today: dt.date | None = None) -> bool:
    """True when there is material to test and the last quiz is `every_days` old."""
    today = today or local_today()
    has_material = db.query(VocabCard).count() > 0 or db.query(DiaryEntry).count() > 0
    if not has_material:
        return False
    last = last_quiz_day(db)
    return last is None or (today - last).days >= every_days


# ── Manual-coding drills ──────────────────────────────────────────────

DRILL_SYSTEM = (
    "You are a strict but friendly programming mentor. Give ONE small coding "
    "exercise on the requested topic that the student must write BY HAND, with no "
    "AI and no copy-paste. Include: the task, 2-3 requirements, one example "
    "input/output, and one hint. Do NOT include the solution. Under 150 words. "
    "Reply in Uzbek; keep code and technical terms in English."
)


def drill_text(provider, topic: str) -> str:
    topic = (topic or "").strip() or "Python basics"
    if not getattr(provider, "ai_available", False):
        return "💻 Mashq yaratish uchun Claude ulangan bo'lishi kerak (/effort bilan tekshiring)."
    reply = provider.chat(f"Topic: {topic}", system=DRILL_SYSTEM)
    return (
        f"💻 Qo'lda yozish mashqi — {topic}\n\n{reply}\n\n"
        "⏱ 20 daqiqa. AI va nusxa ko'chirishsiz yozing. Tugagach, vazifa va kodni "
        "shu yerga yuboring — tekshirib beraman."
    )


# ── Command router ────────────────────────────────────────────────────

def handle_study(db, provider, text: str) -> str | None:
    """Reply to a study command, or to a plain-text answer while a quiz is
    running. Returns None when the message is not a study message."""
    t = (text or "").strip()
    low = t.lower()
    first = low.split()[0] if low.split() else ""
    rest = t[len(first):].strip() if first.startswith("/") else ""

    if first == "/words":
        return words_text(db)
    if first == "/word":
        if not rest:
            return "Foydalanish:\n/word ephemeral - qisqa muddatli\n(Bir nechta so'z — har biri yangi qatorda)"
        added, skipped = add_words(db, rest)
        if not added and not skipped:
            return "Format: so'z - ma'no  (masalan: /word abide - rioya qilmoq)"
        msg = f"✅ Qo'shildi: {added} ta so'z"
        if skipped:
            msg += f" (takror: {skipped})"
        return msg + "\n/review — takrorlash"
    if first == "/learned":
        if not rest:
            return "Foydalanish: /learned bugun Python'da list comprehension o'rgandim..."
        append_diary(db, "learned", rest)
        return "📥 Saqlandi (input).\n\nEndi qaramasdan eslab /recall bilan yozing — shunda yaxshi yodda qoladi."
    if first == "/recall":
        if not rest:
            return "Foydalanish: /recall list comprehension — bu ... (o'zingizcha, qaramasdan)"
        append_diary(db, "recalled", rest)
        return "📤 Saqlandi (output). Zo'r — esdan yozish eng yaxshi mashq! 🔥"
    if first == "/diary":
        return diary_text(db, week=rest.lower() in ("week", "hafta"))
    if first == "/quiz":
        return stop_quiz(db) if rest.lower() == "stop" else start_quiz(db, provider)
    if first == "/drill":
        return drill_text(provider, rest)

    if not t.startswith("/") and active_quiz(db) is not None:
        return answer_quiz(db, provider, t)
    return None
