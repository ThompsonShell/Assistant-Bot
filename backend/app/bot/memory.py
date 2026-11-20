"""The assistant's memory: recent conversation + facts the owner saved.

Every Claude call is independent (the CLI keeps no session), so the bot has to
hand over what it should know each time:

  * the last messages of the conversation (``recent_history``), stored in the
    same ``chat_messages`` table the dashboard chat uses
  * facts saved with /remember, or by saying "eslab qol: ..." (``MemoryFact``)
  * today's date, so "ertaga" and "bu hafta" mean something
"""
from __future__ import annotations

import datetime as dt
import re

from ..models.conversation import ChatMessage, MemoryFact
from ..study import service as study
from .ui import Reply, do

MAX_FACTS = 60
FACT_LEN = 300
HISTORY_MESSAGES = 16        # last 8 exchanges
HISTORY_CHARS = 6000         # budget across the whole history
MESSAGE_CHARS = 700          # long answers are shortened when replayed

_WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def recent_history(db) -> list[dict]:
    """Newest messages that fit the budget, oldest first, starting with the owner."""
    rows = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(HISTORY_MESSAGES).all()
    picked: list[dict] = []
    used = 0
    for row in rows:  # newest first, so the freshest context is kept when over budget
        content = row.content if len(row.content) <= MESSAGE_CHARS else row.content[: MESSAGE_CHARS - 1] + "…"
        if used + len(content) > HISTORY_CHARS and picked:
            break
        picked.append({"role": row.role, "content": content})
        used += len(content)
    picked.reverse()
    while picked and picked[0]["role"] != "user":  # the API wants a conversation that opens with the owner
        picked.pop(0)
    return picked


def remember_turn(db, user_text: str, reply: str) -> None:
    db.add(ChatMessage(role="user", content=user_text, ai_generated=False))
    db.add(ChatMessage(role="assistant", content=reply, ai_generated=True))
    db.commit()


def list_facts(db) -> list[MemoryFact]:
    return db.query(MemoryFact).order_by(MemoryFact.id).all()


def add_fact(db, text: str) -> tuple[MemoryFact | None, str]:
    """Save a fact. Returns (fact, "") or (None, reason)."""
    text = " ".join((text or "").split())
    if not text:
        return None, "Nimani eslab qolishim kerak? Matnni yozing."
    if len(text) > FACT_LEN:
        return None, f"Juda uzun ({len(text)} belgi). {FACT_LEN} belgigacha qisqartiring yoki bir nechta qilib yuboring."
    if any(f.text.lower() == text.lower() for f in list_facts(db)):
        return None, "Bu allaqachon eslab qolingan."
    if db.query(MemoryFact).count() >= MAX_FACTS:
        return None, f"{MAX_FACTS} ta fakt to'ldi. Keraksizini /forget bilan o'chiring."
    fact = MemoryFact(text=text)
    db.add(fact)
    db.commit()
    return fact, ""


def forget(db, fact_id: int) -> bool:
    fact = db.get(MemoryFact, fact_id)
    if fact is None:
        return False
    db.delete(fact)
    db.commit()
    return True


def system_prompt(db, base: str) -> str:
    """The assistant's instructions plus today's date and the saved facts."""
    today = study.local_today()
    parts = [base, f"Bugun: {today.isoformat()} ({_WEEKDAYS[today.weekday()]})."]
    facts = list_facts(db)
    if facts:
        parts.append(
            "What the owner asked you to remember (treat as true):\n"
            + "\n".join(f"- {f.text}" for f in facts)
        )
    parts.append(
        "You can see the recent conversation. Use it and the facts above; never ask the "
        "owner to repeat something that is already there."
    )
    return "\n\n".join(parts)


# ── commands ──────────────────────────────────────────────────────────

_INTENT = re.compile(
    r"^\s*(?:eslab\s*qol|yodda\s*tut|esingda\s*tut|remember(?:\s+that)?)\b\s*[:,\-]?\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)


# Uzbek is typed with several apostrophe characters; store them all as a plain '.
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


def intent_fact(text: str) -> str | None:
    """"eslab qol: men Django o'rganyapman" -> "men Django o'rganyapman"."""
    m = _INTENT.match((text or "").translate(_APOSTROPHES))
    return m.group(1).strip() if m else None


def facts_reply(db) -> Reply:
    facts = list_facts(db)
    if not facts:
        return Reply(
            "🧠 Hali hech narsa eslab qolinmagan.\n\n"
            "Masalan: Men Python/Django o'rganyapman, maqsad 3 oyda junior backend.\n"
            "Bir marta yozsangiz, har yangi chatda ham bilib turaman.",
            [[do("➕ Eslab qol", "/remember")]],
        )
    lines = ["🧠 Men eslab qolganlarim:", ""]
    lines += [f"{i}. {f.text}" for i, f in enumerate(facts, 1)]
    lines.append("\nO'chirish: pastdagi tugma yoki /forget <raqam>")
    delete = [do(f"🗑 {i}", f"/forget {f.id}") for i, f in enumerate(facts[:8], 1)]
    grid = [delete[i:i + 4] for i in range(0, len(delete), 4)]
    grid.append([do("➕ Eslab qol", "/remember")])
    return Reply("\n".join(lines), grid)


def handle_memory(db, text: str) -> str | None:
    """/remember <text> and /forget <n>. None for any other message."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/remember":
        if not arg:
            return "Foydalanish: /remember Men Python o'rganyapman"
        fact, why = add_fact(db, arg)
        return f"🧠 Eslab qoldim: {fact.text}" if fact else why
    if cmd == "/forget":
        if not arg.lstrip("#").isdigit():
            return "Foydalanish: /forget <raqam>  (raqamlar: /memory)"
        return "🗑 Unutdim." if forget(db, int(arg.lstrip("#"))) else "Bunday fakt topilmadi."
    return None
