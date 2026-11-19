"""Scheduled study nudges sent to the owner's Telegram.

  - remind_review: "N words are due" with a Start button (only when N > 0)
  - remind_diary:  evening nudge when today's diary is still empty
  - remind_quiz:   suggest a quiz when the last one is old enough

Each one only messages the owner chat, does nothing when there is nothing to
say, and never raises (the scheduler must keep running).
"""
from __future__ import annotations

import logging
from typing import Callable

import httpx

from ..config import settings
from ..bot import views
from ..study import reading, service as study

logger = logging.getLogger("lifeos.jobs.study")

Message = tuple[str, dict | None]


def _run(session_local, http: httpx.Client | None, build: Callable[..., Message | None]) -> bool:
    if not (settings.telegram_bot_token and settings.telegram_chat_id and settings.study_enabled):
        return False
    from .telegram_bot import send_message

    own = http is None
    client = http or httpx.Client(timeout=30)
    try:
        with session_local() as db:
            msg = build(db)
        if msg is None:
            return False
        text, markup = msg
        send_message(client, settings.telegram_chat_id, text, reply_markup=markup)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("study reminder failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return False
    finally:
        if own:
            client.close()


def remind_review(session_local, http: httpx.Client | None = None) -> bool:
    def build(db) -> Message | None:
        n = len(study.due_cards(db, study.local_today()))
        if n == 0:
            return None
        button = {"inline_keyboard": [[{"text": "▶️ Boshlash", "callback_data": "rv:start"}]]}
        return f"🔁 {n} ta so'zni takrorlash vaqti keldi!", button

    return _run(session_local, http, build)


def remind_diary(session_local, http: httpx.Client | None = None) -> bool:
    """Evening nudge: ask for today's paper diary photo (text /diary is the fallback).
    Skipped when a confirmed photo exists or the text diary already has input and output."""
    def build(db) -> Message | None:
        today = study.local_today()
        items = views.diary_items(db, today)
        if items["photo"] or (items["learned"] and items["recalled"]):
            return None
        status = views.paper_status(db, today)
        streak = study.diary_streak(db, today)
        if status == "pending":
            text = "📷 Qog'oz kundalik o'qildi, lekin tasdiqlanmagan. Rasmdagi xabardagi Tasdiqlash tugmasini bosing."
        else:
            text = (
                "📷 Bugungi qog'oz kundalikni rasmga olib yuboring.\n"
                "Qog'oz bo'lmasa, matnda yozing."
            )
        text += f"\n🔥 Ketma-ket: {streak} kun, uzib qo'ymang!"
        return text, {"inline_keyboard": [[{"text": "📓 Matnda yozish", "callback_data": "do:/diary"}]]}

    return _run(session_local, http, build)


def remind_quiz(session_local, http: httpx.Client | None = None) -> bool:
    def build(db) -> Message | None:
        every = settings.study_quiz_every_days
        if not study.quiz_due(db, every):
            return None
        return f"🧪 Imtihon vaqti (har {every} kunda). Tayyormisiz?\n\n/quiz — boshlash", None

    return _run(session_local, http, build)


def remind_reading(session_local, http: httpx.Client | None = None) -> bool:
    """On Monday, Friday and Sunday: nudge about the planned reading until it is done."""
    def build(db) -> Message | None:
        today = study.local_today()
        kind = reading.assignment_kind(today)
        if kind is None:
            return None
        done = (
            db.query(study.ReadingLog)
            .filter(study.ReadingLog.day == today, study.ReadingLog.kind == kind,
                    study.ReadingLog.status == "done")
            .first()
        )
        if done is not None:
            return None
        return (
            f"📰 Bugun reading kuni: {reading.KIND_LABEL[kind]}\n"
            "15–20 daqiqa. /read — boshlash"
        ), None

    return _run(session_local, http, build)


def remind_unconfirmed(session_local, http: httpx.Client | None = None) -> int:
    """Next morning: show each paper entry still waiting for confirmation, once.

    Returns how many were sent. An entry is marked as asked before sending, so a
    failure can never turn into repeated messages.
    """
    if not (settings.telegram_bot_token and settings.telegram_chat_id and settings.study_enabled):
        return 0
    from ..bot import paper_flow
    from ..study import paper
    from .telegram_bot import send_message

    with session_local() as db:
        entries = paper.unconfirmed_before(db, study.local_today())
        replies = [paper_flow.summary_reply(e, "(tasdiqlanmagan)") for e in entries]
        for e in entries:
            e.reminded = True
        db.commit()
    if not replies:
        return 0

    own = http is None
    client = http or httpx.Client(timeout=30)
    try:
        for reply in replies:
            send_message(client, settings.telegram_chat_id,
                         "📷 Tasdiqlanmagan kundalik:\n\n" + reply.text, reply_markup=reply.markup())
    except Exception as exc:  # noqa: BLE001
        logger.warning("unconfirmed reminder failed", extra={"extra_fields": {"error": str(exc)[:200]}})
    finally:
        if own:
            client.close()
    return len(replies)
