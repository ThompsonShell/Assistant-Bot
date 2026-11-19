"""Screens that are more than one line of text: menu, today, "Yana"; plus the
rule for the single best next action shown under a reply."""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..models.study import DiaryEntry, ReadingLog, VocabCard
from ..models.task import Task
from ..study import reading, service as study
from . import registry
from .ui import Button, Reply, do

# Replies that mean "nothing here yet": command -> (text marker, button that fixes it).
EMPTY_STATES: dict[str, tuple[str, Button]] = {
    "/words": ("Hali so'z yo'q", do("➕ So'z qo'shish", "/word")),
    "/tasks": ("Vazifa yo'q", do("📅 Reja tuzish", "/plan")),
    "/readlog": ("Hali o'qish yo'q", do("📖 O'qishni boshlash", "/read")),
    "/quiz": ("material yo'q", do("➕ So'z qo'shish", "/word")),
    "/github": ("hodisa yo'q", do("📆 Haftani ko'rish", "/github week")),
    "/tried": ("Hali texnik o'qish yo'q", do("📖 Texnik maqola", "/read tech")),
    "/jira": ("hali ulanmagan", do("🏠 Menyu", "/menu")),
    "/channels": ("kuzatilmayapti", do("🏠 Menyu", "/menu")),
}


def empty_state_button(cmd: str, reply_text: str) -> Button | None:
    marker = EMPTY_STATES.get(cmd)
    if marker and marker[0].lower() in reply_text.lower():
        return marker[1]
    return None


# ── diary progress (used by the menu, /bugun and the next-action rule) ──

def diary_items(db, today: dt.date) -> dict[str, bool]:
    entry = db.query(DiaryEntry).filter(DiaryEntry.day == today).first()
    words_today = (
        db.query(VocabCard)
        .filter(VocabCard.created_at >= dt.datetime.combine(today, dt.time.min, dt.timezone.utc))
        .count()
    )
    return {
        "learned": bool(entry and (entry.learned or "").strip()),
        "recalled": bool(entry and (entry.recalled or "").strip()),
        "words": words_today > 0,
    }


def _diary_line(items: dict[str, bool]) -> str:
    return "".join("✅" if v else "▫️" for v in items.values()) + f" {sum(items.values())}/{len(items)}"


# ── best next action ────────────────────────────────────────────────────

def best_next(db, skip: str | None = None) -> Button:
    """The single most useful thing to do now, as a button.

    Order: finish a running quiz, review due cards, complete today's diary,
    write the summary of an open reading, otherwise back to the menu.
    ``skip`` is the command just run, so the bot doesn't suggest it again.
    """
    today = study.local_today()
    candidates: list[tuple[str, Button]] = []
    if study.active_quiz(db) is not None:
        candidates.append(("/quiz", do("🛑 Imtihonni to'xtatish", "/quiz stop")))
    due = len(study.due_cards(db, today))
    if due:
        candidates.append(("/review", do(f"🔁 Takrorlash ({due})", "/review")))
    if not all(diary_items(db, today).values()):
        candidates.append(("/diary", do("📓 Kundalikni to'ldirish", "/diary")))
    if db.query(ReadingLog).filter(ReadingLog.status == "open").first() is not None:
        candidates.append(("/summary", do("📝 Xulosa yozish", "/summary")))
    for cmd, button in candidates:
        if cmd != skip:
            return button
    return do("🏠 Menyu", "/menu")


# ── screens ──────────────────────────────────────────────────────────────

MENU_ROWS = [
    [do("📅 Bugun", "/bugun"), do("📓 Kundalik", "/diary")],
    [do("➕ So'z qo'shish", "/word"), do("🔁 Takrorlash", "/review")],
    [do("🧪 Imtihon", "/quiz"), do("📈 Statistika", "/stats")],
    [do("➕ Yana", "/more")],
]


def main_menu(db) -> Reply:
    today = study.local_today()
    due = len(study.due_cards(db, today))
    items = diary_items(db, today)
    lines = ["🏠 Asosiy menyu", ""]
    lines.append(f"🔁 Takrorlash: {due} ta so'z" if due else "🔁 Takrorlash: bugunlik tayyor")
    lines.append(f"📓 Kundalik: {_diary_line(items)}")
    lines.append("\nQuyidagidan tanlang:")
    return Reply("\n".join(lines), [list(r) for r in MENU_ROWS])


def more_screen() -> Reply:
    rows: list[list[Button]] = [
        [do("📊 GitHub bugun", "/today"), do("📅 Vazifalar", "/tasks")],
        [do("📖 Maqola o'qish", "/read"), do("💻 Kod mashqi", "/drill")],
        [do("🌤 Ob-havo", "/weather")],
    ]
    if registry.is_available(next(c for c in registry.COMMANDS if c.name == "news")):
        rows.append([do("🌍 Yangiliklar", "/news"), do("🚀 Kosmos", "/news space")])
    extra: list[Button] = []
    for name, label in (("jira", "📋 Jira"), ("channels", "📣 Kanallar")):
        if registry.is_available(next(c for c in registry.COMMANDS if c.name == name)):
            extra.append(do(label, f"/{name}"))
    if extra:
        rows.append(extra)
    rows.append([do("🧠 Claude chuqurligi", "/effort"), do("🏠 Menyu", "/menu")])
    return Reply(registry.full_list_text(), rows)


def _open_tasks(db, today: dt.date) -> list[Task]:
    return (
        db.query(Task)
        .filter(Task.status != "done")
        .filter((Task.scheduled_date <= today) | (Task.scheduled_date.is_(None)))
        .order_by(Task.scheduled_date.is_(None), Task.scheduled_date)
        .limit(20)
        .all()
    )


def today_view(db) -> Reply:
    """One screen: tasks, cards due, diary progress, planned reading, quiz."""
    today = study.local_today()
    lines = [f"📅 Bugun — {today.strftime('%a %d-%b')}", ""]

    tasks = _open_tasks(db, today)
    if tasks:
        lines.append(f"📋 Vazifalar: {len(tasks)} ta")
        lines += [f"  ▫️ #{t.id} {t.title}" for t in tasks[:3]]
        if len(tasks) > 3:
            lines.append(f"  … yana {len(tasks) - 3} ta (/tasks)")
    else:
        lines.append("📋 Vazifalar: yo'q")

    due = len(study.due_cards(db, today))
    lines.append(f"🔁 Takrorlash: {due} ta so'z" if due else "🔁 Takrorlash: tayyor")
    lines.append(f"📓 Kundalik: {_diary_line(diary_items(db, today))}")

    kind = reading.assignment_kind(today)
    if kind:
        done = (
            db.query(ReadingLog)
            .filter(ReadingLog.day == today, ReadingLog.kind == kind, ReadingLog.status == "done")
            .first()
        )
        lines.append(f"📖 {reading.KIND_LABEL[kind]}: {'✅ bajarildi' if done else 'bugun /read'}")
    if study.quiz_due(db, settings.study_quiz_every_days, today):
        lines.append("🧪 Imtihon vaqti keldi")
    return Reply("\n".join(lines)).with_next(best_next(db, skip="/today"))
