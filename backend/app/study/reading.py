"""Weekly article-reading routine for the bot.

The plan: Monday a vocabulary text from the course book, Friday a technical
article matching the week's topic, Sunday a space/NASA article. Each reading
takes 15-20 minutes and follows the same steps:

  1. check the length (400-800 words at first, longer from month 3)
  2. read once without a dictionary
  3. send at most 5 unknown words to the bot (they become flashcards)
  4. write a 2-sentence English summary
  5. for documentation: try one example in code

Commands: /read [vocab|tech|space], /topic, /summary, /tried, /readlog.
While a reading is open, /word is capped at 5 new words so reading stays fast.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
from urllib.parse import quote_plus

import httpx

from ..config import settings
from ..integrations.news import NewsItem, fetch_news, parse_feed, shorten
from ..models.study import ReadingLog, StudyKV
from . import service as study

logger = logging.getLogger("lifeos.reading")

KIND_BY_WEEKDAY = {0: "vocab", 4: "tech", 6: "space"}  # Mon, Fri, Sun
KIND_LABEL = {
    "vocab": "📖 Reading & Words matni",
    "tech": "💻 Texnik maqola",
    "space": "🚀 Kosmos / NASA maqolasi",
}
WORD_CAP = 5
_DAY_NAMES = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


# ── schedule ──────────────────────────────────────────────────────────

def assignment_kind(day: dt.date) -> str | None:
    """Which reading is planned for a date, or None on a free day."""
    return KIND_BY_WEEKDAY.get(day.weekday())


def next_reading_day(day: dt.date) -> tuple[dt.date, str]:
    for i in range(1, 8):
        d = day + dt.timedelta(days=i)
        kind = assignment_kind(d)
        if kind:
            return d, kind
    raise RuntimeError("unreachable")  # a reading day exists every week


def target_words(start: dt.date, today: dt.date) -> tuple[int, int]:
    """Length range: short articles first, longer ones from month 3."""
    months = max(0, (today - start).days) // 30
    return (400, 800) if months < 2 else (800, 1500)


# ── small key/value settings ──────────────────────────────────────────

def get_kv(db, key: str, default: str = "") -> str:
    row = db.get(StudyKV, key)
    return row.value if row is not None and row.value else default


def set_kv(db, key: str, value: str) -> None:
    row = db.get(StudyKV, key)
    if row is None:
        db.add(StudyKV(key=key, value=value))
    else:
        row.value = value
    db.commit()


def reading_start(db, today: dt.date) -> dt.date:
    """The day reading began (set the first time /read is used)."""
    raw = get_kv(db, "reading_start")
    if raw:
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            pass
    set_kv(db, "reading_start", today.isoformat())
    return today


# ── choosing an article ───────────────────────────────────────────────

def resources_for(topic: str) -> list[tuple[str, str, bool]]:
    """Reading sources for a topic as (name, url, is_documentation)."""
    t = (topic or "").lower()
    q = quote_plus(topic or "python")
    out: list[tuple[str, str, bool]] = []
    if any(k in t for k in ("django", "drf", "rest", "api", "orm")):
        out.append(("Django docs", f"https://docs.djangoproject.com/en/stable/search/?q={q}", True))
        out.append(("Django REST framework", "https://www.django-rest-framework.org/", True))
    if any(k in t for k in ("sql", "postgres", "database", "query", "index")):
        out.append(("PostgreSQL docs", f"https://www.postgresql.org/search/?q={q}", True))
    if any(k in t for k in ("git", "shell", "bash", "terminal", "vim", "command")):
        out.append(("Missing Semester", "https://missing.csail.mit.edu/", True))
    out.append(("Real Python", f"https://realpython.com/search?q={q}", False))
    return out


def topic_score(item: NewsItem, topic: str) -> int:
    words = [w for w in re.findall(r"\w+", (topic or "").lower()) if len(w) >= 3]
    text = f"{item.title} {item.summary}".lower()
    return sum(1 for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text))


def fetch_feed_items(urls: list[str], http: httpx.Client) -> list[NewsItem]:
    """Items from the given feeds; a broken feed is skipped."""
    items: list[NewsItem] = []
    for url in urls:
        try:
            resp = http.get(url)
            resp.raise_for_status()
            items += parse_feed(resp.text, re.sub(r"^https?://(www\.)?", "", url).split("/")[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("reading feed failed", extra={"extra_fields": {"error": str(exc)[:200]}})
    return items


def estimate_words(url: str, http: httpx.Client) -> int | None:
    """Rough article length from the paragraphs on its page (None if unreadable)."""
    try:
        resp = http.get(url, timeout=10)
        resp.raise_for_status()
        paragraphs = _P_RE.findall(resp.text[:400_000])
    except Exception:  # noqa: BLE001
        return None
    text = html.unescape(" ".join(_TAG_RE.sub(" ", p) for p in paragraphs))
    return len(re.findall(r"\w+", text)) or None


def pick_article(
    items: list[NewsItem], lo: int, hi: int, read_urls: set[str], http: httpx.Client,
    max_checks: int = 6,
) -> tuple[NewsItem | None, int | None]:
    """First unread article whose length fits [lo, hi] (with some slack).
    Falls back to the first unread one when no length could be confirmed."""
    fresh = [i for i in items if i.link not in read_urls]
    for item in fresh[:max_checks]:
        n = estimate_words(item.link, http)
        if n and lo * 0.75 <= n <= hi * 1.25:
            return item, n
    return (fresh[0] if fresh else None), None


# ── starting a reading ────────────────────────────────────────────────

def _steps(kind: str, lo: int, hi: int) -> str:
    lines = [
        "",
        f"🎯 Uzunligi: {lo}–{hi} so'z · ⏱ 15–20 daqiqa",
        "",
        "1️⃣ Birinchi o'qish: lug'atga qaramang, umumiy ma'noni tushuning",
        f"2️⃣ Noma'lum so'zlar: /word so'z - ma'no (ko'pi bilan {WORD_CAP} ta)",
        "3️⃣ Xulosa: /summary This article explains... The main idea is...",
    ]
    if kind != "vocab":
        lines.append("4️⃣ Hujjat bo'lsa: bitta misolni o'zingiz kodda sinang, so'ng /tried")
    return "\n".join(lines)


def _render(log: ReadingLog, lo: int, hi: int, extra: str = "") -> str:
    lines = [f"📚 {KIND_LABEL[log.kind]}", "", log.title]
    if log.blurb:
        lines += ["", log.blurb]
    if log.url:
        lines += ["", f"🔗 {log.url}"]
    if extra:
        lines += ["", extra]
    return "\n".join(lines) + "\n" + _steps(log.kind, lo, hi)


def _open_log(db, today: dt.date, kind: str | None = None) -> ReadingLog | None:
    q = db.query(ReadingLog).filter(ReadingLog.status == "open", ReadingLog.day == today)
    if kind:
        q = q.filter(ReadingLog.kind == kind)
    return q.order_by(ReadingLog.id.desc()).first()


def start_reading(db, kind: str, today: dt.date | None = None) -> str:
    today = today or study.local_today()
    lo, hi = target_words(reading_start(db, today), today)

    existing = _open_log(db, today, kind)
    if existing is not None:  # same reading again: don't create a duplicate
        return _render(existing, lo, hi, "ℹ️ Bugungi o'qish allaqachon boshlangan.")

    title, url, blurb, extra = "Darslikdagi bugungi Reading & Words matni", None, None, ""
    if kind != "vocab":
        read_urls = {u for (u,) in db.query(ReadingLog.url).filter(ReadingLog.url.is_not(None))}
        topic = get_kv(db, "topic")
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as http:
                if kind == "tech":
                    feeds = [u.strip() for u in settings.reading_tech_feeds.split(",") if u.strip()]
                    items = sorted(
                        fetch_feed_items(feeds, http), key=lambda i: -topic_score(i, topic)
                    )
                    if topic:  # only articles that actually match the weekly topic
                        items = [i for i in items if topic_score(i, topic) > 0]
                else:
                    items = fetch_news(limit=15, http=http, topic="space")
                item, words = pick_article(items, lo, hi, read_urls, http)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reading pick failed", extra={"extra_fields": {"error": str(exc)[:200]}})
            item, words = None, None

        if item is not None:
            title, url, blurb = item.title[:300], item.link[:1000], (item.summary or None)
            if words:
                extra = f"Taxminan {words} so'z."
        elif kind == "tech":
            title = f"Mavzu bo'yicha maqola tanlang: {topic or 'Python'}"
            extra = "Maqola avtomatik topilmadi. Manbalar:\n" + "\n".join(
                f"• {n}: {u}" for n, u, _ in resources_for(topic)
            )
        else:
            title = "Kosmos maqolasini tanlang"
            extra = "Maqola topilmadi. /news space dan tanlang."

    log = ReadingLog(day=today, kind=kind, title=title, url=url, blurb=blurb)
    db.add(log)
    db.commit()
    return _render(log, lo, hi, extra)


# ── the five steps ────────────────────────────────────────────────────

def add_reading_words(db, log: ReadingLog, rest: str, today: dt.date) -> str:
    """/word while a reading is open: at most WORD_CAP words per reading."""
    parsed = study.parse_words(rest)
    if not parsed:
        return "Format: so'z - ma'no  (masalan: /word abide - rioya qilmoq)"
    remaining = WORD_CAP - (log.words_sent or 0)
    if remaining <= 0:
        return (
            f"🛑 {WORD_CAP} ta limit to'ldi. Qolgan so'zlarni o'tkazib yuboring — "
            "aks holda o'qish sekinlashadi.\nXulosani yozing: /summary ..."
        )
    use = parsed[:remaining]
    text = "\n".join(f"{w} - {m}" + (f" | {e}" if e else "") for w, m, e in use)
    added, skipped = study.add_words(db, text, today)
    log.words_sent = (log.words_sent or 0) + added
    db.commit()
    msg = f"✅ Qo'shildi: {added} ta ({log.words_sent}/{WORD_CAP})"
    if skipped:
        msg += f" · takror: {skipped}"
    if len(parsed) > len(use):
        msg += f"\n⚠️ Limit sababli {len(parsed) - len(use)} ta so'z o'tkazib yuborildi."
    return msg


SUMMARY_SYSTEM = (
    "You are an English teacher for a Python learner. The learner wrote a "
    "2-sentence summary of an article. Reply in Uzbek, max 60 words: fix grammar "
    "mistakes, show the corrected version in English, and say if it states the main idea."
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def save_summary(db, provider, text: str, today: dt.date) -> str:
    log = (
        db.query(ReadingLog)
        .filter(ReadingLog.status == "open")
        .order_by(ReadingLog.id.desc())
        .first()
    )
    if log is None:
        return "Ochiq o'qish yo'q. Avval /read bilan boshlang."
    if not text.strip():
        return "Foydalanish: /summary This article explains... The main idea is..."

    log.summary = text.strip()[:1000]
    log.status = "done"
    db.commit()
    study.append_diary(db, "recalled", f"[Reading] {log.title}: {text.strip()}", today)

    hints = []
    n = len(_sentences(text))
    if n != 2:
        hints.append(f"ℹ️ Reja 2 ta gap: sizda {n} ta.")
    if "main idea" not in text.lower():
        hints.append("ℹ️ Ikkinchi gapni 'The main idea is...' bilan boshlang.")
    lines = [f"📝 Xulosa saqlandi ({log.title[:60]})."] + hints
    if getattr(provider, "ai_available", False):
        try:
            lines += ["", provider.chat(text, system=SUMMARY_SYSTEM)]
        except Exception:  # noqa: BLE001
            pass
    lines.append(f"\nNoma'lum so'zlar: {log.words_sent}/{WORD_CAP} · 🔥 Kundalikka ham yozildi.")
    if log.kind != "vocab":
        lines.append("💻 Hujjat bo'lsa: bitta misolni kodda sinang va /tried deb yozing.")
    return "\n".join(lines)


def mark_tried(db) -> str:
    log = (
        db.query(ReadingLog)
        .filter(ReadingLog.kind != "vocab")
        .order_by(ReadingLog.id.desc())
        .first()
    )
    if log is None:
        return "Hali texnik o'qish yo'q. /read tech"
    log.example_done = True
    db.commit()
    return f"✅ Zo'r! Misolni sinadingiz: {log.title[:60]}"


def readlog_text(db, limit: int = 8) -> str:
    logs = db.query(ReadingLog).order_by(ReadingLog.id.desc()).limit(limit).all()
    if not logs:
        return "📚 Hali o'qish yo'q. /read bilan boshlang."
    lines = ["📚 So'nggi o'qishlar:"]
    for lg in logs:
        mark = "✅" if lg.status == "done" else "⏳"
        extras = f"{lg.words_sent} so'z" + (" · 💻" if lg.example_done else "")
        lines.append(f"{mark} {lg.day.strftime('%d-%b')} {lg.kind}: {shorten(lg.title, 50)} ({extras})")
    return "\n".join(lines)


# ── command router ────────────────────────────────────────────────────

def handle_reading(db, provider, text: str) -> str | None:
    """Reply to a reading command, or None if the message isn't one."""
    t = (text or "").strip()
    parts = t.split(maxsplit=1)
    first = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    today = study.local_today()

    if first == "/read":
        kind = rest.lower()
        if kind in ("vocab", "tech", "space"):
            return start_reading(db, kind, today)
        planned = assignment_kind(today)
        if planned:
            return start_reading(db, planned, today)
        d, nxt = next_reading_day(today)
        return (
            f"Bugun reading kuni emas. Keyingisi: {_DAY_NAMES[d.weekday()]} — {KIND_LABEL[nxt]}.\n"
            "Xohlasangiz hozir: /read tech yoki /read space"
        )
    if first == "/topic":
        with_topic = rest.strip()
        if not with_topic:
            current = get_kv(db, "topic")
            return f"🧭 Haftalik mavzu: {current or 'belgilanmagan'}\nO'zgartirish: /topic pytest"
        set_kv(db, "topic", with_topic[:100])
        return f"🧭 Haftalik mavzu: {with_topic}\nJuma kuni shu mavzuga mos maqola tanlanadi."
    if first == "/summary":
        return save_summary(db, provider, rest, today)
    if first == "/tried":
        return mark_tried(db)
    if first == "/readlog":
        return readlog_text(db)
    if first == "/word" and rest:
        log = _open_log(db, today)
        if log is not None:
            return add_reading_words(db, log, rest, today)
    return None
