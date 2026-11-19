"""Telegram side of the paper diary: photo -> summary -> follow-ups -> Confirm.

All functions work on a db session and return a :class:`Reply`; the Telegram
module only downloads the photo and sends what comes back.

Buttons use the ``pe:`` prefix: ``pe:ok:<id>`` confirm, ``pe:edit:<id>``
choose a field, ``pe:f:<id>:<key>`` edit one field, ``pe:z:<id>:<key>`` set a
number to 0, ``pe:skip:<id>`` stop the follow-up questions, ``pe:date:<id>``
wrong date, ``pe:retake:<id>`` discard and send again, ``pe:addw:<id>`` add the
proposed words, ``pe:del:<id>`` delete (after /delete_entry).
"""
from __future__ import annotations

import datetime as dt

from ..models.study import PaperEntry
from ..study import paper, service as study
from . import state
from .ui import Reply, do

CANCEL = ("❌ Bekor qilish", "do:/cancel")


def _snip(text: str, n: int = 160) -> str:
    """Shorten for the summary; separate lines stay visible as " · "."""
    text = " · ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return text if len(text) <= n else text[: n - 1] + "…"


# ── summary ───────────────────────────────────────────────────────────

def summary_reply(entry: PaperEntry, note: str = "") -> Reply:
    """What the bot understood from the page, with the four action buttons."""
    m = entry.minutes or {}

    def num(v) -> str:
        return "—" if v is None else str(v)

    lines = [f"📷 Qog'oz kundalik — {entry.day.isoformat()}" + (f" {note}" if note else "")]
    lines.append(
        "⏱ " + " · ".join(f"{label} {num(m.get(key))}" for key, label in paper.CATEGORIES)
        + f" | AI-off: {num(entry.ai_off_minutes)}"
    )
    total = paper.total_minutes(entry)
    lines.append(f"   Jami: {total // 60} s {total % 60} d")
    parsed = entry.parsed or {}
    for key, label in paper.TEXT_FIELDS:
        if parsed.get(key):
            lines.append(f"{label}: {_snip(parsed[key])}")
    if len(entry.photo_paths or []) > 1:
        lines.append(f"🖼 Rasmlar: {len(entry.photo_paths)}")
    lines += ["", "To'g'rimi? Tasdiqlamaguncha statistikaga qo'shilmaydi."]

    i = entry.id
    rows = [
        [("✅ Tasdiqlash", f"pe:ok:{i}"), ("✏️ Tahrirlash", f"pe:edit:{i}")],
        [("📅 Sana noto'g'ri", f"pe:date:{i}"), ("🔁 Qayta rasm", f"pe:retake:{i}")],
    ]
    return Reply("\n".join(lines), rows)


def edit_picker(entry: PaperEntry) -> Reply:
    m = entry.minutes or {}
    i = entry.id
    minute_buttons = []
    for key, label in paper.CATEGORIES:
        v = m.get(key)
        minute_buttons.append((f"{label} {'—' if v is None else v}", f"pe:f:{i}:{key}"))
    v = entry.ai_off_minutes
    minute_buttons.append((f"AI-off {'—' if v is None else v}", f"pe:f:{i}:aioff"))
    text_buttons = [(label, f"pe:f:{i}:{key}") for key, label in paper.TEXT_FIELDS]

    def chunk(items, n=3):
        return [items[k:k + n] for k in range(0, len(items), n)]

    rows = chunk(minute_buttons) + chunk(text_buttons) + [[("⬅️ Orqaga", f"pe:sum:{i}")]]
    return Reply("✏️ Qaysi maydonni o'zgartiramiz?", rows)


# ── follow-up questions for missing numbers ───────────────────────────

def _minutes_question(key: str) -> str:
    return "AI'siz (AI-off) necha daqiqa?" if key == "aioff" else f"{paper.LABEL[key]} necha daqiqa?"


def ask_next(db, entry: PaperEntry, note: str = "", intro: bool = False) -> Reply:
    """Ask for the next missing number, or show the summary when none is left."""
    miss = paper.missing_fields(entry)
    if not miss:
        state.clear_state(db)
        return summary_reply(entry, note)
    key = miss[0]
    state.set_state(db, "paper:min", {"id": entry.id, "key": key, "chain": True, "note": note})
    head = f"📷 Sahifa o'qildi: {entry.day.isoformat()} {note}\n\n" if intro else ""
    i = entry.id
    return Reply(
        head + _minutes_question(key),
        [[("0 daqiqa", f"pe:z:{i}:{key}"), ("⏭ Keyinroq", f"pe:skip:{i}")]],
    )


# ── a photo arrives ───────────────────────────────────────────────────

def handle_photo(db, provider, data: bytes, caption: str = "", suffix: str = ".jpg") -> Reply:
    today = study.local_today()

    chosen, source = paper.caption_date(caption), "caption"
    if chosen is None:
        chosen, source = paper.pop_next_date(db), "command"
    if chosen is not None:
        err = paper.backfill_error(chosen, today)
        if err:
            return Reply(f"{err}\n\nBoshqa sana bilan qayta yuboring.", [[do("📷 Qo'llanma", "/photo")]])

    path = paper.save_photo_file(data, suffix)
    page, failure = None, ""
    try:
        page = paper.read_page(provider, path)
    except paper.PaperError as exc:  # no vision, or the call failed: keep the photo, type the numbers
        failure = exc.user_message

    if page is not None and (
        not page["readable"] or not (page["transcription"] or any(page[k] for k, _ in paper.TEXT_FIELDS))
    ):
        paper.remove_files([path])  # never keep or invent anything from an unreadable page
        return Reply(
            "📷 Sahifani o'qib bo'lmadi. Yorug' joyda, to'g'ri burchakdan qayta suratga oling.",
            [[do("📷 Qo'llanma", "/photo")]],
        )

    page_date = page["date"] if page else None
    if chosen is not None:
        day = chosen
        note = "(izohdan)" if source == "caption" else "(/date)"
    elif page_date is not None and paper.backfill_error(page_date, today) is None:
        day, note = page_date, "(rasmdan o'qildi)"
    elif page_date is not None:
        day, note = today, f"(rasmdagi sana {page_date.isoformat()} mos kelmadi, bugun deb olindi)"
    else:
        day, note = today, "(rasmda sana yo'q, bugun deb olindi)"
    if failure:
        note += f"\n⚠️ {failure} Rasm saqlandi, maydonlarni qo'lda kiriting."

    entry = paper.add_page(db, day, path, page)
    return ask_next(db, entry, note, intro=True)


# ── typed answers while a paper question is open ──────────────────────

def _entry_or_clear(db, data) -> PaperEntry | None:
    entry = paper.get_entry(db, int(data.get("id", 0)))
    if entry is None:
        state.clear_state(db)
    return entry


def answer(db, st: tuple[str, dict], text: str) -> Reply:
    kind, data = st
    today = study.local_today()
    text = text.strip()

    if kind in ("paper:min", "paper:text", "paper:date"):
        entry = _entry_or_clear(db, data)
        if entry is None:
            return Reply("Yozuv topilmadi.", [[do("🏠 Menyu", "/menu")]])

        if kind == "paper:date":
            day = paper.parse_date(text)
            if day is None:
                return Reply("Sanani 2026-11-20 shaklida yozing.", [[CANCEL]])
            err = paper.move_to_day(db, entry, day, today)
            if err:
                return Reply(f"{err}\nBoshqa sanani yozing.", [[CANCEL]])
            state.clear_state(db)
            return summary_reply(entry, "(sana o'zgartirildi)")

        err = paper.set_field(db, entry, data["key"], text)
        if err:
            return Reply(err, [[CANCEL]])
        if kind == "paper:min" and data.get("chain"):
            return ask_next(db, entry, data.get("note", ""))
        state.clear_state(db)
        return summary_reply(entry)

    if kind == "paper:setdate":
        day = paper.parse_date(text)
        err = "Sanani 2026-11-20 shaklida yozing." if day is None else paper.backfill_error(day, today)
        if err:
            return Reply(err, [[CANCEL]])
        return _set_next_date(db, day)

    if kind == "paper:deldate":
        day = paper.parse_date(text)
        if day is None:
            return Reply("Sanani 2026-11-20 shaklida yozing.", [[CANCEL]])
        return _ask_delete(db, day)

    state.clear_state(db)
    return Reply("Savol eskirgan.", [[do("🏠 Menyu", "/menu")]])


# ── button taps ───────────────────────────────────────────────────────

def on_callback(db, parts: list[str]) -> Reply | None:
    """Handle ``pe:...`` buttons. Returns what to send, or None."""
    if len(parts) < 3 or not parts[2].isdigit():
        return None
    action, entry = parts[1], paper.get_entry(db, int(parts[2]))
    if entry is None:
        return Reply("Yozuv topilmadi (o'chirilgan bo'lishi mumkin).", [[do("🏠 Menyu", "/menu")]])
    key = parts[3] if len(parts) > 3 else ""

    if action == "sum":
        return summary_reply(entry)
    if action == "edit":
        return edit_picker(entry)
    if action == "ok":
        return _confirmed(db, entry)
    if action == "f" and key in paper.LABEL:
        if key in paper.MINUTE_KEYS:
            state.set_state(db, "paper:min", {"id": entry.id, "key": key, "chain": False})
            return Reply(_minutes_question(key), [[CANCEL]])
        state.set_state(db, "paper:text", {"id": entry.id, "key": key})
        return Reply(f"{paper.LABEL[key]}: yangi matnni yozing.", [[CANCEL]])
    if action == "z" and key in paper.MINUTE_KEYS:
        paper.set_field(db, entry, key, "0")
        return ask_next(db, entry)
    if action == "skip":
        state.clear_state(db)
        return summary_reply(entry)
    if action == "date":
        state.set_state(db, "paper:date", {"id": entry.id})
        return Reply(f"📅 Bu sahifa qaysi kunga tegishli? Hozir: {entry.day.isoformat()}\nYangi sanani yozing (2026-11-20):", [[CANCEL]])
    if action == "retake":
        if entry.confirmed:
            return Reply("Bu yozuv tasdiqlangan. O'chirish: /delete_entry " + entry.day.isoformat(),
                         [[do("🏠 Menyu", "/menu")]])
        paper.delete_entry(db, entry)
        state.clear_state(db)
        return Reply("🔁 Eski rasm o'chirildi. Yangi rasmni yuboring.", [[do("📷 Qo'llanma", "/photo")]])
    if action == "addw":
        n = paper.add_proposed_words(db, entry)
        return Reply(f"✅ {n} ta so'z kartochkaga qo'shildi." if n else "Yangi so'z yo'q (hammasi allaqachon bor).")
    if action == "del":
        day = entry.day
        paper.delete_entry(db, entry)
        return Reply(f"🗑 {day.isoformat()} yozuvi va rasmlari o'chirildi.", [[do("🏠 Menyu", "/menu")]])
    return None


def _confirmed(db, entry: PaperEntry) -> Reply:
    result = paper.confirm(db, entry)
    total = paper.total_minutes(entry)
    lines = [
        f"✅ Saqlandi: {entry.day.isoformat()} — {total // 60} s {total % 60} d",
        f"🔥 Ketma-ket: {result.streak} kun",
    ]
    rows = []
    if result.word_pairs:
        lines.append("📚 So'z takliflari:")
        lines += [f"  • {w} — {m}" for w, m in result.word_pairs]
        rows.append([(f"➕ {len(result.word_pairs)} ta so'zni qo'shish", f"pe:addw:{entry.id}")])
    if result.loose_words:
        lines.append("Ma'nosi yozilmagan: " + ", ".join(result.loose_words) + " (/word bilan qo'shing)")
    return Reply("\n".join(lines), rows)


# ── /date and /delete_entry ───────────────────────────────────────────

def _set_next_date(db, day: dt.date) -> Reply:
    from ..study.reading import set_kv

    set_kv(db, "next_photo_date", day.isoformat())
    state.clear_state(db)
    return Reply(f"📅 Keyingi rasm {day.isoformat()} sanasi uchun hisoblanadi.", [[do("📷 Qo'llanma", "/photo")]])


def _ask_delete(db, day: dt.date) -> Reply:
    state.clear_state(db)
    entry = paper.entry_for_day(db, day)
    if entry is None:
        return Reply(f"{day.isoformat()} uchun qog'oz yozuv yo'q.", [[do("📓 Kundalik", "/diary")]])
    return Reply(
        f"🗑 {day.isoformat()} yozuvi va uning rasmlari o'chirilsinmi? Qaytarib bo'lmaydi.",
        [[("🗑 Ha, o'chirish", f"pe:del:{entry.id}"), ("↩️ Yo'q", "do:/menu")]],
    )


def command(db, cmd: str, text: str) -> Reply | None:
    """Reply to /date or /delete_entry, or None for any other command."""
    if cmd not in ("/date", "/delete_entry"):
        return None
    parts = text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    today = study.local_today()

    if cmd == "/date":
        if not arg:
            state.set_state(db, "paper:setdate", {})
            return Reply("📅 Keyingi rasm qaysi kun uchun? Sanani yozing (2026-11-20):", [[CANCEL]])
        day = paper.parse_date(arg)
        err = "Sanani 2026-11-20 shaklida yozing." if day is None else paper.backfill_error(day, today)
        return Reply(err) if err else _set_next_date(db, day)

    if not arg:
        state.set_state(db, "paper:deldate", {})
        return Reply("🗑 Qaysi kunning yozuvi o'chirilsin? Sanani yozing (2026-11-20):", [[CANCEL]])
    day = paper.parse_date(arg)
    return Reply("Sanani 2026-11-20 shaklida yozing.") if day is None else _ask_delete(db, day)
