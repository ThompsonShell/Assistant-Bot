"""Guided conversations: a command sent without arguments asks one short
question, waits for the next message, saves it and confirms.

"/command text" in a single message keeps working; the flow just collects the
same text and runs the same code. A new command cancels a pending question.
"""
from __future__ import annotations

from collections.abc import Callable

from ..models.study import ReadingLog
from ..models.task import Task
from ..study import service as study
from . import state
from .ui import Reply, do

CANCEL_ROW = [do("❌ Bekor qilish", "/cancel")]

QUESTIONS: dict[str, str] = {
    "/word": "➕ Qaysi so'z? Shunday yozing: so'z - ma'no\n(bir nechta bo'lsa, har birini yangi qatordan)",
    "/learned": "📥 Bugun nimani o'rgandingiz? Qisqa yozing.",
    "/recall": "📤 Qaramasdan, esingizda qolganini o'zingizcha yozing.",
    "/summary": "📝 Maqola xulosasini ingliz tilida 2 gapda yozing:\nThis article explains... The main idea is...",
    "/plan": "📅 Qanday reja tuzay? Masalan: bu hafta backend, ingliz tili, dashboard.",
    "/done": "✅ Qaysi vazifa raqami? (ro'yxat: /tasks)",
    "/topic": "🧭 Haftalik mavzu nima? Masalan: pytest",
    "/drill": "💻 Qaysi mavzuda mashq kerak? Masalan: python lists",
}


def _precheck(db, cmd: str) -> Reply | None:
    """Skip the question when the command cannot work yet (empty state)."""
    if cmd == "/summary" and db.query(ReadingLog).filter(ReadingLog.status == "open").first() is None:
        return Reply(
            "Ochiq o'qish yo'q. Avval maqola oling.", [[do("📖 O'qishni boshlash", "/read")]]
        )
    if cmd == "/done" and db.query(Task).filter(Task.status != "done").first() is None:
        return Reply("Vazifa yo'q. Avval reja tuzing.", [[do("📅 Reja tuzish", "/plan")]])
    return None


def _invalid(cmd: str, text: str) -> str | None:
    """A short hint when the answer can't be used, so the question is asked again."""
    if cmd == "/word" and not study.parse_words(text):
        return "Format: so'z - ma'no  (masalan: abide - rioya qilmoq)"
    if cmd == "/done":
        words = text.strip().lstrip("#").split()
        if not words or not words[0].isdigit():
            return "Raqam yozing (masalan: 3)"
    return None


def start(db, cmd: str) -> Reply | None:
    """Begin a flow for a bare command, or None if the command has no flow."""
    if cmd not in QUESTIONS:
        return None
    blocked = _precheck(db, cmd)
    if blocked is not None:
        return blocked
    state.set_state(db, f"flow:{cmd}")
    return Reply(QUESTIONS[cmd], [list(CANCEL_ROW)])


def pending_command(db) -> str | None:
    """The command whose answer the bot is waiting for, if any."""
    st = state.get_state(db)
    if st and st[0].startswith("flow:"):
        return st[0][len("flow:"):]
    return None


def answer(db, cmd: str, text: str, run: Callable[[str], str]) -> Reply:
    """Use the owner's message as the argument of ``cmd``.

    ``run`` executes the one-message form ("/word abide - ...") and returns its
    reply text. If the answer is unusable the question is asked again.
    """
    hint = _invalid(cmd, text)
    if hint:
        return Reply(f"{hint}\n\n{QUESTIONS[cmd]}", [list(CANCEL_ROW)])
    state.clear_state(db)
    return Reply(run(f"{cmd} {text.strip()}"))
