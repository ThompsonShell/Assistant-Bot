"""Two-way Telegram bot (long-polling).

Responds ONLY to the configured owner (settings.telegram_chat_id); every other
chat is politely refused. Supports commands (/today, /week, /github, /repos)
and free-text chat routed to the AI provider.

Run standalone:  python -m app.jobs.telegram_bot
Also started as a daemon thread by the app factory when a token + chat id are set.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import httpx

from ..analytics import compute_range, github_summary
from ..config import settings
from ..db import make_engine, make_sessionmaker
from ..models.github import GitHubEvent, GitHubRepo
from ..models.task import Task
from ..providers import get_provider

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _week_start() -> dt.date:
    """Return the Monday of the current week (used as the anchor for plans)."""
    today = dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _date_for_day(day: Any, week_start: dt.date):
    """Map a weekday name (e.g. "Monday") to its date in the given week.

    Returns None when ``day`` is missing or not a recognized weekday, so a
    task without a specific day stays unscheduled.
    """
    if isinstance(day, str) and day.lower() in _DAYS:
        return week_start + dt.timedelta(days=_DAYS.index(day.lower()))
    return None

logger = logging.getLogger("lifeos.telegram")

HELP = (
    "👋 *Private AI LifeOS*\n\n"
    "Buyruqlar:\n"
    "/today — bugungi GitHub faoliyati\n"
    "/week — haftalik statistika\n"
    "/month — oylik statistika\n"
    "/github — oxirgi hodisalar\n"
    "/repos — kuzatilayotgan repolar\n"
    "📅 /plan <matn> — AI reja tuzadi va saqlaydi\n"
    "📅 /tasks — vazifalar ro'yxati\n"
    "📅 /done <raqam> — bajarildi deb belgilash\n"
    "🌤 /weather — ob-havo va nima kiyish tavsiyasi\n"
    "/effort — Claude chuqurligi (low/medium/high)\n"
    "/help — yordam\n\n"
    "Oddiy matn yozsangiz — Claude javob beradi (ulangan bo'lsa)."
)

SYSTEM_PROMPT = (
    "You are the owner's private personal assistant inside their Telegram bot. "
    "Be concise, friendly, and helpful. Reply in the same language the user writes in "
    "(often Uzbek). You help with productivity, planning, and their GitHub activity."
)


def _api(method: str) -> str:
    """Build the full Telegram Bot API URL for a given method."""
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


BOT_COMMANDS = [
    {"command": "today", "description": "Bugungi GitHub faoliyati"},
    {"command": "week", "description": "Haftalik statistika"},
    {"command": "github", "description": "Oxirgi hodisalar"},
    {"command": "repos", "description": "Kuzatilayotgan repolar"},
    {"command": "plan", "description": "AI reja tuzish (saqlaydi)"},
    {"command": "tasks", "description": "Vazifalar ro'yxati"},
    {"command": "done", "description": "Vazifa bajarildi"},
    {"command": "weather", "description": "Ob-havo va kiyim tavsiyasi"},
    {"command": "effort", "description": "Claude chuqurligi"},
    {"command": "help", "description": "Yordam"},
]

# Persistent quick-tap buttons shown after /start.
MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "/tasks"}, {"text": "/today"}],
        [{"text": "/plan "}, {"text": "/help"}],
    ],
    "resize_keyboard": True,
}


def send_message(http: httpx.Client, chat_id: Any, text: str, reply_markup=None) -> None:
    """Send a message to a chat, truncating to Telegram's limit.

    Failures are logged and swallowed so a transient send error never crashes
    the polling loop. ``reply_markup`` optionally attaches a keyboard.
    """
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        http.post(_api("sendMessage"), json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram send failed", extra={"extra_fields": {"error": str(exc)[:200]}})


def set_bot_commands(http: httpx.Client) -> None:
    """Register the "/" menu of commands with Telegram."""
    try:
        http.post(_api("setMyCommands"), json={"commands": BOT_COMMANDS})
    except Exception as exc:  # noqa: BLE001
        logger.warning("setMyCommands failed", extra={"extra_fields": {"error": str(exc)[:200]}})


def _summary_text(db, range_name: str) -> str:
    """Format the GitHub activity summary for a named range (today/week/month)."""
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
    """Format the most recent GitHub events (newest first) as a chat message."""
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
    """Format the list of watched repositories as a chat message."""
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
    if low in ("/weather", "/obhavo", "/ob-havo"):
        return _weather_text()
    if low == "/effort" or low.startswith("/effort "):
        return _effort_text(t)
    if low == "/tasks":
        return _tasks_text(db)
    if low.startswith("/plan"):
        plan_text = t[len("/plan"):].strip()
        if not plan_text:
            return "Reja matnini yozing: /plan bu hafta backend, ingliz tili, dashboard..."
        return _plan_and_save(db, provider, plan_text)
    if low.startswith("/done"):
        return _mark_done(db, t)
    if t.startswith("/"):
        return "Noma'lum buyruq. /help ni bosing."
    return provider.chat(t, system=SYSTEM_PROMPT, history=history)


def _plan_and_save(db, provider, text: str) -> str:
    """Ask the AI provider to plan tasks from free text, persist them, and
    return a confirmation listing each saved task with its day and duration."""
    result = provider.plan_tasks(text)
    if not result.tasks:
        return result.summary or "Vazifa topilmadi."
    week = _week_start()
    saved = []
    for item in result.tasks:
        task = Task(
            title=item.get("title", "Task"),
            scheduled_date=_date_for_day(item.get("day"), week),
            duration_minutes=item.get("duration_minutes"),
            priority=item.get("priority") or "medium",
            category=item.get("category"),
            source="ai",
        )
        db.add(task)
        saved.append(task)
    db.commit()
    for t in saved:
        db.refresh(t)
    lines = [f"📅 {result.summary}".strip(), ""]
    for t in saved:
        when = t.scheduled_date.strftime("%a %d-%b") if t.scheduled_date else "kunsiz"
        dur = f", {t.duration_minutes} min" if t.duration_minutes else ""
        lines.append(f"#{t.id} {t.title} ({when}{dur})")
    if result.notes:
        lines.append("\n❓ " + " ".join(result.notes))
    lines.append("\n✅ Saqlandi. /tasks — ko'rish, /done <raqam> — bajarildi.")
    return "\n".join(lines)


def _tasks_text(db) -> str:
    """List every open (not-done) task as a message.

    Overdue tasks are kept — an unfinished task scheduled earlier must not
    silently vanish once its day has passed; it is marked ``⚠️ kechikdi``.
    Dated tasks come first (earliest first), then undated ones.
    """
    today = dt.date.today()
    tasks = (
        db.query(Task)
        .filter(Task.status != "done")
        .order_by(Task.scheduled_date.is_(None), Task.scheduled_date)
        .limit(20)
        .all()
    )
    if not tasks:
        return "Vazifa yo'q. /plan bilan reja tuzing."
    lines = ["📋 Vazifalar:"]
    for t in tasks:
        when = t.scheduled_date.strftime("%a %d-%b") if t.scheduled_date else "kunsiz"
        overdue = " ⚠️ kechikdi" if t.scheduled_date and t.scheduled_date < today else ""
        lines.append(f"▫️ #{t.id} {t.title} ({when}){overdue}")
    lines.append("\n/done <raqam> — bajarildi deb belgilash.")
    return "\n".join(lines)


def _mark_done(db, text: str) -> str:
    """Mark the task from a "/done <id>" command as completed.

    Returns a usage hint for a malformed command or a not-found message when
    no task matches the id.
    """
    parts = text.split()
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        return "Foydalanish: /done <raqam>  (masalan: /done 3)"
    tid = int(parts[1].lstrip("#"))
    task = db.get(Task, tid)
    if task is None:
        return f"#{tid} topilmadi."
    task.status = "done"
    task.completed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return f"✅ Bajarildi: {task.title}"


def _weather_text() -> str:
    """/weather — current weather for the configured city plus a clothing tip.

    Network/parse errors are caught and reported as a friendly message so the
    command never crashes the bot.
    """
    from ..integrations.weather import clothing_advice, fetch_weather

    try:
        w = fetch_weather()
    except Exception as exc:  # noqa: BLE001
        logger.warning("weather fetch failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return "🌡 Ob-havo ma'lumotini olib bo'lmadi. Keyinroq urinib ko'ring."
    return (
        f"{w.emoji} *{w.city}* — hozir\n"
        f"🌡 {w.temp:.0f}°C (his: {w.feels_like:.0f}°C)\n"
        f"☁️ {w.description.capitalize()} · 💨 {w.wind:.0f} km/soat\n\n"
        f"👕 *Kiyim tavsiyasi:*\n{clothing_advice(w)}"
    )


def _effort_text(text: str) -> str:
    """/effort — show or set Claude reasoning effort."""
    from ..providers.runtime import VALID_EFFORTS, get_effort, set_effort

    parts = text.split()
    if len(parts) < 2:
        return (
            f"🧠 Hozirgi effort: *{get_effort()}*\n\n"
            "O'zgartirish: /effort <low|medium|high|xhigh|max>\n"
            "• medium — tez va tejamkor (tavsiya)\n"
            "• high — chuqurroq, lekin sekinroq va obunadan ko'proq sarflaydi"
        )
    level = parts[1].lower()
    if level not in VALID_EFFORTS:
        return "Noto'g'ri daraja. /effort <low|medium|high|xhigh|max>"
    set_effort(level)
    return f"✅ Effort o'rnatildi: {level}"


def process_update(http, session_local, provider, update: dict) -> None:
    """Handle one Telegram update: reject non-owner chats, route the text
    through :func:`handle_text`, and reply (with the main keyboard on /start)."""
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
    markup = MAIN_KEYBOARD if text.strip().lower() in ("/start", "start") else None
    send_message(http, chat_id, reply, reply_markup=markup)


def run_bot(
    *, session_local=None, http=None, provider=None, max_iterations: int | None = None
) -> None:
    """Run the long-polling loop: fetch updates and process them one by one.

    No-ops when the token or chat id is unset. ``max_iterations`` bounds the
    loop for tests; in production it runs forever, keeping alive through errors.
    """
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        logger.info("telegram bot disabled: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return

    if session_local is None:
        engine = make_engine(settings.database_url)
        session_local = make_sessionmaker(engine)
    http = http or httpx.Client(timeout=70)
    provider = provider or get_provider()

    set_bot_commands(http)  # register the "/" command menu
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
    """Entry point for running the bot standalone (``python -m ...``)."""
    from ..logging_config import configure_logging

    configure_logging(settings.log_level)
    run_bot()


if __name__ == "__main__":
    _main()
