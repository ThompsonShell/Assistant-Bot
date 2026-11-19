"""Screens that are more than one line of text: menu, today, "Yana"; plus the
rule for the single best next action shown under a reply."""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..models.study import DiaryEntry, PaperEntry, ReadingLog, VocabCard
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


# ── diary progress (used by the menu, /bugun, /diary and the next-action rule) ──

WORDS_TARGET = 3  # the paper template has "3 WORDS" per day


def words_today(db, today: dt.date) -> int:
    since = dt.datetime.combine(today, dt.time.min, dt.timezone.utc)
    return db.query(VocabCard).filter(VocabCard.created_at >= since).count()


def paper_status(db, today: dt.date) -> str:
    """"confirmed", "pending" (photo read, not confirmed) or "none"."""
    entry = db.query(PaperEntry).filter(PaperEntry.day == today).first()
    if entry is None:
        return "none"
    return "confirmed" if entry.confirmed else "pending"


def diary_items(db, today: dt.date) -> dict[str, bool]:
    entry = db.query(DiaryEntry).filter(DiaryEntry.day == today).first()
    return {
        "learned": bool(entry and (entry.learned or "").strip()),
        "recalled": bool(entry and (entry.recalled or "").strip()),
        "words": words_today(db, today) >= WORDS_TARGET,
        "photo": paper_status(db, today) == "confirmed",
    }


def diary_complete(items: dict[str, bool]) -> bool:
    """The day counts as done without a photo: text input/output and the words
    are enough (paper is the preferred way, /diary text is the fallback)."""
    return items["learned"] and items["recalled"] and items["words"]


def _diary_line(items: dict[str, bool]) -> str:
    return "".join("✅" if v else "▫️" for v in items.values()) + f" {sum(items.values())}/{len(items)}"


def diary_checklist(db) -> Reply:
    """Today's diary as a checklist, with a button for every missing item."""
    today = study.local_today()
    items = diary_items(db, today)
    n_words = words_today(db, today)
    photo = paper_status(db, today)

    def mark(ok: bool) -> str:
        return "✅" if ok else "▫️"

    lines = [
        f"📓 Kundalik — {today.strftime('%a %d-%b')} · 🔥 {study.diary_streak(db, today)} kun",
        "",
        f"{mark(items['learned'])} 📥 O'rgandim (input)",
        f"{mark(items['recalled'])} 📤 Yodimdan yozdim (output)",
        f"{'✅' if items['words'] else '🟡' if n_words else '▫️'} 📚 So'zlar: {n_words}/{WORDS_TARGET}",
        f"{'✅' if photo == 'confirmed' else '🟡' if photo == 'pending' else '▫️'} 📷 Qog'oz kundalik"
        + (" (tasdiqlanmagan)" if photo == "pending" else ""),
    ]
    rows: list[list[Button]] = []
    if not items["learned"]:
        rows.append([do("📥 O'rgandim", "/learned")])
    if not items["recalled"]:
        rows.append([do("📤 Yodimdan", "/recall")])
    if not items["words"]:
        rows.append([do("➕ So'z qo'shish", "/word")])
    if photo == "none":
        rows.append([do("📷 Rasm yuborish", "/photo")])
    if not rows:
        lines += ["", "🎉 Bugun hammasi tayyor!"]
        rows.append([best_next(db, skip="/diary")])
    return Reply("\n".join(lines), rows)


PAPER_TEMPLATE = """DATE: 2026-__-__
TIME (min): Python __  SQL __  English __  Algo __  Other __   | AI-off: __
LEARNED (input):
WROTE MYSELF (output):
MISTAKES:
3 WORDS:
QUESTION:
TOMORROW:"""


def photo_help() -> Reply:
    return Reply(
        "📷 Qog'oz kundalik\n\n"
        "Bugungi sahifaning rasmini shu yerga yuboring (bir nechta rasm ham mumkin). "
        "Bot o'qiydi va sizdan tasdiq so'raydi. Tasdiqlamaguncha statistikaga qo'shilmaydi.\n\n"
        "Sahifa tepasiga shuni yozing:\n" + PAPER_TEMPLATE + "\n\n"
        "Maslahat: raqamlar aniq, har yorliq alohida qatorda, sana 2026-11-20 shaklida.\n"
        "Boshqa kun uchun: rasm izohiga date: 2026-11-19 yozing (48 soatgacha).",
        [[do("📓 Matnda yozish", "/learned")]],
    )


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
    if not diary_complete(diary_items(db, today)):
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
