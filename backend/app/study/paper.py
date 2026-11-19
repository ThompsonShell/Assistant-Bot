"""Paper diary by photo (master plan section 7b).

The owner writes a page by hand, sends a photo, the bot reads it with vision,
shows what it understood and waits for Confirm. Only confirmed entries count
in statistics. Rules the code keeps:

  * transcribe faithfully, never "fix" or invent text; unreadable -> retake
  * a missing number is asked for, never guessed
  * the date comes from the caption, then /date, then the page, then today,
    and the owner can always say "wrong date"
  * backfilling is allowed only within DIARY_BACKFILL_HOURS (48 h)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings
from ..models.study import DiaryEntry, PaperEntry
from ..providers.base import extract_json
from . import service as study

logger = logging.getLogger("lifeos.paper")

CATEGORIES = [("python", "Python"), ("sql", "SQL"), ("english", "English"), ("algo", "Algo"), ("other", "Other")]
TEXT_FIELDS = [
    ("learned", "📥 O'rgandim"),
    ("output", "📤 Yozdim"),
    ("mistakes", "❌ Xatolar"),
    ("words", "📚 So'zlar"),
    ("question", "❓ Savol"),
    ("tomorrow", "➡️ Ertaga"),
]
MINUTE_KEYS = [k for k, _ in CATEGORIES] + ["aioff"]
LABEL = dict(CATEGORIES) | {"aioff": "AI-off"} | dict(TEXT_FIELDS)


class PaperError(Exception):
    """Reading failed; ``user_message`` is safe to show to the owner."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class NoVision(PaperError):
    """The connected AI provider cannot read images."""


# ── reading the page with vision ──────────────────────────────────────

PAGE_SYSTEM = (
    "You read a photo of ONE handwritten diary page. The writer mixes Uzbek and "
    "English. The page has these labelled lines: DATE, TIME (min): Python, SQL, "
    "English, Algo, Other and AI-off, LEARNED (input), WROTE MYSELF (output), "
    "MISTAKES, 3 WORDS, QUESTION, TOMORROW.\n"
    "Rules: transcribe faithfully; NEVER correct, translate, summarise or invent "
    "anything. Write [?] for unreadable parts. Use null for anything missing or "
    "unreadable; never guess a number or a date.\n"
    "Reply with ONLY this JSON: {\"readable\": bool, \"transcription\": str, "
    "\"date\": \"YYYY-MM-DD\"|null, \"minutes\": {\"python\": int|null, \"sql\": int|null, "
    "\"english\": int|null, \"algo\": int|null, \"other\": int|null}, \"ai_off\": int|null, "
    "\"learned\": str, \"output\": str, \"mistakes\": str, \"words\": str, "
    "\"question\": str, \"tomorrow\": str}. \"readable\" is false if the page "
    "cannot be read at all."
)


def _int(value: Any) -> int | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 1440 else None


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


parse_date = _date  # public name for the Telegram layer


def parse_page(raw: str) -> dict[str, Any] | None:
    """Validate the model's JSON. Returns None when it is not usable JSON."""
    data = extract_json(raw or "")
    if not isinstance(data, dict):
        return None
    minutes_in = data.get("minutes") if isinstance(data.get("minutes"), dict) else {}
    minutes = {k: _int(minutes_in.get(k)) for k, _ in CATEGORIES}
    if sum(v or 0 for v in minutes.values()) > 1440:  # more than a day: don't trust any of it
        minutes = {k: None for k, _ in CATEGORIES}
    out: dict[str, Any] = {
        "readable": bool(data.get("readable", True)),
        "transcription": str(data.get("transcription") or "").strip()[:6000],
        "date": _date(data.get("date")),
        "minutes": minutes,
        "ai_off": _int(data.get("ai_off")),
    }
    for key, _ in TEXT_FIELDS:
        out[key] = str(data.get(key) or "").strip()[:3000]
    return out


def read_page(provider, image_path: str) -> dict[str, Any]:
    """Send the photo to the AI provider and return the parsed page.

    Raises NoVision when the provider cannot read images and PaperError when
    the call fails or the answer is unusable.
    """
    vision = getattr(provider, "vision", None)
    if vision is None or not getattr(provider, "ai_available", False):
        raise NoVision("Rasmni o'qish uchun Claude ulangan bo'lishi kerak.")
    try:
        raw = vision(
            "Transcribe this diary page and fill the JSON.", image_path, system=PAGE_SYSTEM
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("diary vision failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        raise PaperError(f"Rasmni o'qishda xato: {str(exc)[:120]}") from exc
    page = parse_page(raw)
    if page is None:
        raise PaperError("Javobni tushunib bo'lmadi.")
    return page


# ── dates ─────────────────────────────────────────────────────────────

_CAPTION_DATE = re.compile(r"date\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def caption_date(caption: str) -> dt.date | None:
    m = _CAPTION_DATE.search(caption or "")
    return _date(m.group(1)) if m else None


def backfill_error(day: dt.date, today: dt.date) -> str | None:
    """Why ``day`` cannot be used, or None. Future days and days older than the
    backfill window are refused."""
    if day > today:
        return f"{day.isoformat()} kelajak sanasi."
    limit = max(1, -(-settings.diary_backfill_hours // 24))  # hours -> whole days, rounded up
    if (today - day).days > limit:
        return f"{day.isoformat()} juda eski: faqat {settings.diary_backfill_hours} soatgacha qo'shish mumkin."
    return None


def pop_next_date(db) -> dt.date | None:
    """The date set with /date for the next photo (and forget it)."""
    from .reading import get_kv, set_kv

    raw = get_kv(db, "next_photo_date")
    if not raw:
        return None
    set_kv(db, "next_photo_date", "")
    return _date(raw)


# ── storing photos ────────────────────────────────────────────────────

def save_photo_file(data: bytes, suffix: str = ".jpg") -> str:
    """Write the photo into the private folder (owner-only permissions)."""
    folder = Path(settings.diary_photo_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"{stamp}{suffix if suffix in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return str(path)


def remove_files(paths: list[str]) -> None:
    for p in paths:
        try:
            Path(p).unlink()
        except OSError:
            pass


# ── entries ───────────────────────────────────────────────────────────

def get_entry(db, entry_id: int) -> PaperEntry | None:
    return db.get(PaperEntry, entry_id)


def entry_for_day(db, day: dt.date) -> PaperEntry | None:
    return db.query(PaperEntry).filter(PaperEntry.day == day).first()


def add_page(db, day: dt.date, photo_path: str | None, page: dict[str, Any] | None) -> PaperEntry:
    """Create the day's entry, or append to it (a second photo for the same day).

    Appending keeps numbers already read (no double counting), fills the missing
    ones, joins text, and asks for confirmation again.
    """
    page = page or {}
    entry = entry_for_day(db, day)
    if entry is None:
        entry = PaperEntry(day=day, photo_paths=[], transcription="", parsed={}, minutes={})
        db.add(entry)
    if photo_path:
        entry.photo_paths = [*entry.photo_paths, photo_path]
    if page.get("transcription"):
        entry.transcription = (
            f"{entry.transcription}\n---\n{page['transcription']}" if entry.transcription else page["transcription"]
        )

    parsed = dict(entry.parsed or {})
    for key, _ in TEXT_FIELDS:
        new = (page.get(key) or "").strip()
        old = (parsed.get(key) or "").strip()
        parsed[key] = f"{old}\n{new}".strip() if old and new else (new or old)
    entry.parsed = parsed

    minutes = dict(entry.minutes or {})
    for key, _ in CATEGORIES:
        if minutes.get(key) is None:
            minutes[key] = (page.get("minutes") or {}).get(key)
    entry.minutes = minutes
    if entry.ai_off_minutes is None:
        entry.ai_off_minutes = page.get("ai_off")

    entry.confirmed, entry.confirmed_at, entry.reminded = False, None, False
    db.commit()
    return entry


def missing_fields(entry: PaperEntry) -> list[str]:
    """Number fields still empty, in the order they are asked."""
    miss = [k for k, _ in CATEGORIES if (entry.minutes or {}).get(k) is None]
    if entry.ai_off_minutes is None:
        miss.append("aioff")
    return miss


def total_minutes(entry: PaperEntry) -> int:
    return sum(v or 0 for v in (entry.minutes or {}).values())


def set_field(db, entry: PaperEntry, key: str, value: str) -> str | None:
    """Set one field from the owner's text. Returns an error message or None."""
    value = value.strip()
    if key in MINUTE_KEYS:
        text = value.lower()
        n = 0 if text in ("0", "yo'q", "yoq", "-", "no") else _int(re.sub(r"\D", "", text) or None)
        if n is None:
            return "Daqiqani raqam bilan yozing (masalan: 90, yo'q bo'lsa 0)."
        if key == "aioff":
            entry.ai_off_minutes = n
        else:
            entry.minutes = {**(entry.minutes or {}), key: n}
    else:
        entry.parsed = {**(entry.parsed or {}), key: value[:3000]}
    entry.confirmed, entry.confirmed_at = False, None
    db.commit()
    return None


def move_to_day(db, entry: PaperEntry, day: dt.date, today: dt.date) -> str | None:
    """Change the entry's date. Refuses invalid dates and days already used."""
    err = backfill_error(day, today)
    if err:
        return err
    other = entry_for_day(db, day)
    if other is not None and other.id != entry.id:
        return f"{day.isoformat()} uchun yozuv allaqachon bor."
    entry.day = day
    entry.confirmed, entry.confirmed_at = False, None
    db.commit()
    return None


def delete_entry(db, entry: PaperEntry) -> None:
    """Remove the entry and its photos from disk."""
    remove_files(list(entry.photo_paths or []))
    db.delete(entry)
    db.commit()


# ── confirm and fan out ───────────────────────────────────────────────

def split_words(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Split the page's "3 WORDS" text into (word, meaning) pairs and loose words.

    A line with a separator ("abide - rioya qilmoq") is a pair; a line without
    one ("abide, abandon") holds loose words that still need a meaning.
    """
    pairs: list[tuple[str, str]] = []
    loose: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        got = study.parse_words(line)
        if got:
            pairs.append((got[0][0], got[0][1]))
        else:
            loose += [w.strip() for w in re.split(r"[,;]", line) if w.strip()]
    return pairs, loose


@dataclass
class Confirmed:
    entry: PaperEntry
    streak: int
    word_pairs: list[tuple[str, str]]      # "word - meaning" lines that can become cards
    loose_words: list[str]                 # words without a meaning


def confirm(db, entry: PaperEntry) -> Confirmed:
    """Mark the entry confirmed and feed the rest of the system.

    Input and output go to the diary (so streaks and reminders see them). Words
    are only *proposed* as cards. Mistakes stay on the entry until an error
    log exists.
    """
    entry.confirmed = True
    entry.confirmed_at = dt.datetime.now(dt.timezone.utc)
    parsed = entry.parsed or {}

    diary = db.query(DiaryEntry).filter(DiaryEntry.day == entry.day).first()
    if diary is None:
        diary = DiaryEntry(day=entry.day, learned="", recalled="")
        db.add(diary)
    if parsed.get("learned"):
        diary.learned = parsed["learned"]
    if parsed.get("output"):
        diary.recalled = parsed["output"]
    db.commit()

    pairs, loose = split_words(parsed.get("words") or "")
    return Confirmed(
        entry=entry,
        streak=study.diary_streak(db, entry.day),
        word_pairs=pairs,
        loose_words=loose,
    )


def add_proposed_words(db, entry: PaperEntry) -> int:
    pairs, _ = split_words((entry.parsed or {}).get("words", ""))
    added, _ = study.add_words(db, "\n".join(f"{w} - {m}" for w, m in pairs))
    return added


def unconfirmed_before(db, today: dt.date) -> list[PaperEntry]:
    """Entries waiting for confirmation that have not been asked about yet."""
    return (
        db.query(PaperEntry)
        .filter(PaperEntry.confirmed.is_(False), PaperEntry.reminded.is_(False), PaperEntry.day < today)
        .order_by(PaperEntry.day)
        .all()
    )
