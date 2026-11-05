"""Two-way Telegram bot (long-polling).

Responds ONLY to the configured owner (settings.telegram_chat_id); every other
chat is politely refused. Supports commands (/today, /week, /github, /repos)
and free-text chat routed to the AI provider.

Run standalone:  python -m app.jobs.telegram_bot
Also started as a daemon thread by the app factory when a token + chat id are set.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ..analytics import compute_range, github_summary
from ..config import settings
from ..db import make_engine, make_sessionmaker
from ..models.github import GitHubEvent, GitHubRepo
from ..providers import get_provider

logger = logging.getLogger("lifeos.telegram")

HELP = (
    "👋 *Private AI LifeOS*\n\n"
    "Buyruqlar:\n"
    "/today — bugungi GitHub faoliyati\n"
    "/week — haftalik statistika\n"
    "/month — oylik statistika\n"
    "/github — oxirgi hodisalar\n"
    "/repos — kuzatilayotgan repolar\n"
    "/help — yordam\n\n"
    "Oddiy matn yozsangiz — Claude javob beradi (ulangan bo'lsa)."
)

SYSTEM_PROMPT = (
    "You are the owner's private personal assistant inside their Telegram bot. "
    "Be concise, friendly, and helpful. Reply in the same language the user writes in "
    "(often Uzbek). You help with productivity, planning, and their GitHub activity."
)


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def send_message(http: httpx.Client, chat_id: Any, text: str) -> None:
    try:
        http.post(_api("sendMessage"), json={"chat_id": chat_id, "text": text[:4000]})
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram send failed", extra={"extra_fields": {"error": str(exc)[:200]}})


def _summary_text(db, range_name: str) -> str:
    start, end = compute_range(range_name, settings.display_timezone)
    a = github_summary(db, start, end)
    return (
        f"📊 {range_name.capitalize()} ({settings.display_timezone})\n"
        f"Commits: {a['commits']}\n"
        f"Hodisalar: {a['total_events']}\n"
        f"Pull requests: {a['pull_requests']}\n"
        f"Issues: {a['issues']}\n"
        f"👤 Odam: {a['human_events']} · 🤖 Avtomatika: {a['automation_events']}"
    )


def _events_text(db, limit: int = 8) -> str:
    events = (
        db.query(GitHubEvent).order_by(GitHubEvent.created_at.desc()).limit(limit).all()
    )
    if not events:
        return "Hali hodisa yo'q. Repo qo'shib, poll qiling."
    lines = ["🔔 Oxirgi hodisalar:"]
    for e in events:
        lines.append(f"• {e.actor_login} {e.title} — {e.repo_full_name}")
    return "\n".join(lines)


def _repos_text(db) -> str:
    repos = db.query(GitHubRepo).order_by(GitHubRepo.full_name).all()
    if not repos:
        return "Kuzatilayotgan repo yo'q."
    return "📁 Repolar:\n" + "\n".join(f"• {r.full_name}" for r in repos)


def handle_text(db, provider, text: str, history: list[dict] | None = None) -> str:
    """Pure routing logic: returns the reply for a given message text."""
    t = (text or "").strip()
    low = t.lower()
    if low in ("/start", "/help", "start", "help"):
        return HELP
    if low == "/today":
        return _summary_text(db, "today")
    if low in ("/week", "/stats"):
        return _summary_text(db, "week")
    if low == "/month":
        return _summary_text(db, "month")
    if low in ("/github", "/events"):
        return _events_text(db)
    if low == "/repos":
        return _repos_text(db)
    if t.startswith("/"):
        return "Noma'lum buyruq. /help ni bosing."
    return provider.chat(t, system=SYSTEM_PROMPT, history=history)


def process_update(http, session_local, provider, update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text") or ""

    # Owner-only: reject everyone else.
    if str(chat_id) != str(settings.telegram_chat_id):
        if chat_id is not None:
            send_message(http, chat_id, "⛔ Bu shaxsiy bot — faqat egasi uchun.")
        logger.info("rejected non-owner chat", extra={"extra_fields": {"chat_id": chat_id}})
        return
    if not text:
        return

    with session_local() as db:
        reply = handle_text(db, provider, text)
    send_message(http, chat_id, reply)


def run_bot(
    *, session_local=None, http=None, provider=None, max_iterations: int | None = None
) -> None:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        logger.info("telegram bot disabled: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return

    if session_local is None:
        engine = make_engine(settings.database_url)
        session_local = make_sessionmaker(engine)
    http = http or httpx.Client(timeout=70)
    provider = provider or get_provider()

    logger.info("telegram bot started (long-polling)")
    offset = None
    iterations = 0
    while True:
        try:
            resp = http.get(_api("getUpdates"), params={"timeout": 50, "offset": offset})
            for upd in resp.json().get("result", []):
                offset = upd["update_id"] + 1
                process_update(http, session_local, provider, upd)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("telegram poll error", extra={"extra_fields": {"error": str(exc)[:200]}})
            time.sleep(3)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break


def _main() -> None:
    from ..logging_config import configure_logging

    configure_logging(settings.log_level)
    run_bot()


if __name__ == "__main__":
    _main()
