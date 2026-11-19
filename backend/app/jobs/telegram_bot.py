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
from zoneinfo import ZoneInfo

import httpx

from ..analytics import compute_range, github_summary
from ..config import settings
from ..db import make_engine, make_sessionmaker
from ..models.github import GitHubEvent, GitHubRepo
from ..models.task import Task
from ..bot import flows, paper_flow, registry, state as bot_state, views
from ..bot.ui import Reply, do
from ..models.study import VocabCard
from ..providers import get_provider
from ..study import reading, service as study

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
    "/github [today|week|month|all] — kim nima qildi\n"
    "/repos — kuzatilayotgan repolar\n"
    "📅 /plan <matn> — AI reja tuzadi va saqlaydi\n"
    "📅 /tasks — vazifalar ro'yxati\n"
    "📅 /done <raqam> — bajarildi deb belgilash\n"
    "📋 /jira — menga tayinlangan Jira issue'lar\n"
    "🌍 /news [space] — texnologiya / kosmos yangiliklari\n"
    "📣 /channels — kuzatilayotgan kanallar\n"
    "🌤 /weather — ob-havo va nima kiyish tavsiyasi\n"
    "📚 /word so'z - ma'no — so'z qo'shish\n"
    "📚 /review — so'z takrorlash (kartochkalar)\n"
    "📚 /words — so'zlar statistikasi\n"
    "📓 /learned <matn> — bugun nimani o'rgandim\n"
    "📓 /recall <matn> — qaramasdan, yodimdan yozdim\n"
    "📓 /diary [week] — kundalik va ketma-ket kunlar\n"
    "🧪 /quiz — imtihon (/quiz stop)\n"
    "💻 /drill <mavzu> — qo'lda yoziladigan kod mashqi\n"
    "📰 /read [tech|space] — bugungi maqola (du: so'z, ju: texnik, yak: kosmos)\n"
    "📰 /summary <matn> — 2 gaplik ingliz xulosasi, /tried — misolni sinadim\n"
    "📰 /topic <mavzu> — haftalik mavzu, /readlog — o'qishlar tarixi\n"
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


# One persistent button next to the text box; it opens the inline main menu.
MENU_BUTTON_TEXT = "🏠 Menyu"
MAIN_KEYBOARD = {
    "keyboard": [[{"text": MENU_BUTTON_TEXT}]],
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


def send_photo(http: httpx.Client, chat_id: Any, photo_url: str, caption: str) -> bool:
    """Send a photo (by URL) with a caption. Returns False when Telegram
    rejects it (e.g. it cannot download the image) so callers can fall back
    to a plain text message."""
    payload = {"chat_id": chat_id, "photo": photo_url, "caption": caption[:1024]}
    try:
        resp = http.post(_api("sendPhoto"), json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram photo failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return False
    status = getattr(resp, "status_code", 200)
    return not (isinstance(status, int) and status >= 400)


def send_card(http: httpx.Client, chat_id: Any, text: str, image: str | None = None) -> None:
    """Send text with an optional image above it; falls back to text only."""
    if image and send_photo(http, chat_id, image, text):
        return
    send_message(http, chat_id, text)


def send_news_cards(
    http: httpx.Client,
    chat_id: Any,
    limit: int = 5,
    heading: str | None = None,
    topic: str = "tech",
) -> int:
    """Send each top tech story as its own card: image, short text, link.

    Returns the number of cards sent. Missing cover images are looked up on the
    article page (bounded); stories without an image are sent as text.
    """
    from ..integrations.news import card_caption, ensure_images, fetch_news

    if not settings.news_enabled:
        return 0
    items = fetch_news(limit=limit, http=http, topic=topic)
    if not items:
        send_message(http, chat_id, "🌍 Hozircha yangilik topilmadi.")
        return 0
    ensure_images(items, http)
    if heading:
        send_message(http, chat_id, heading)
    for item in items:
        send_card(http, chat_id, card_caption(item), item.image)
    return len(items)


def _tg(http: httpx.Client, method: str, payload: dict) -> None:
    """Call a Telegram method, logging (never raising) on failure."""
    try:
        http.post(_api(method), json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"telegram {method} failed", extra={"extra_fields": {"error": str(exc)[:200]}})


def _front_keyboard(card_id: int) -> dict:
    return {"inline_keyboard": [[{"text": "👁 Javobni ko'rsat", "callback_data": f"rv:show:{card_id}"}]]}


def _rating_keyboard(card_id: int) -> dict:
    def btn(label: str, grade: str) -> dict:
        return {"text": label, "callback_data": f"rv:rate:{card_id}:{grade}"}

    return {"inline_keyboard": [
        [btn("❌ Bilmadim", "again"), btn("😐 Qiyin", "hard")],
        [btn("✅ Yaxshi", "good"), btn("⚡️ Oson", "easy")],
    ]}


def send_review_card(http: httpx.Client, chat_id: Any, db, exclude_id: int | None = None) -> bool:
    """Send the next due vocabulary card with a "show answer" button.
    Returns False (and says so) when nothing is due."""
    today = study.local_today()
    card = study.next_card(db, today, exclude_id)
    if card is None:
        if db.query(VocabCard).count() == 0:
            reply = Reply("📚 Hali so'z yo'q.", [[do("➕ So'z qo'shish", "/word")]])
        else:
            reply = Reply("🎉 Bugunlik takrorlash tugadi!").with_next(views.best_next(db, skip="/review"))
        send_message(http, chat_id, reply.text, reply_markup=reply.markup())
        return False
    waiting = len(study.due_cards(db, today))
    send_message(
        http, chat_id, f"{study.card_front(card)}\n\n🔁 Navbatda: {waiting}",
        reply_markup=_front_keyboard(card.id),
    )
    return True


def process_callback(http, session_local, cb: dict, provider=None) -> None:
    """Handle a tap on an inline button (owner only).

    ``do:<command>`` runs the command as if it had been typed; ``rv:`` buttons
    drive the vocabulary review."""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("message_id")
    _tg(http, "answerCallbackQuery", {"callback_query_id": cb.get("id")})
    if str(chat_id) != str(settings.telegram_chat_id):
        return

    data = cb.get("data") or ""
    if data.startswith("do:"):
        _handle_owner_text(http, session_local, provider, chat_id, data[3:])
        return
    parts = data.split(":")
    if parts[0] == "pe":  # paper diary buttons
        with session_local() as db:
            reply = paper_flow.on_callback(db, parts)
            if reply is not None:
                reply.with_next(views.best_next(db))
        if reply is not None:
            _tg(http, "editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},   # a tapped button can't be tapped twice
            })
            send_message(http, chat_id, reply.text, reply_markup=reply.markup())
        return
    if parts[0] != "rv" or len(parts) < 2:
        return
    with session_local() as db:
        if parts[1] == "start":
            send_review_card(http, chat_id, db)
        elif parts[1] == "show" and len(parts) == 3 and parts[2].isdigit():
            card = db.get(VocabCard, int(parts[2]))
            if card is not None:
                _tg(http, "editMessageText", {
                    "chat_id": chat_id, "message_id": message_id,
                    "text": study.card_back(card), "reply_markup": _rating_keyboard(card.id),
                })
        elif parts[1] == "rate" and len(parts) == 4 and parts[2].isdigit():
            card = study.rate_card(db, int(parts[2]), parts[3])
            if card is None:
                return
            when = "bugun yana ko'rsatiladi" if card.interval_days == 0 else f"{card.interval_days} kundan keyin"
            _tg(http, "editMessageText", {
                "chat_id": chat_id, "message_id": message_id,
                "text": f"✅ {card.word} — {card.meaning}\n⏭ {when}",
                "reply_markup": {"inline_keyboard": []},
            })
            send_review_card(http, chat_id, db, exclude_id=card.id)


def set_bot_commands(http: httpx.Client) -> None:
    """Register the "/" menu of commands with Telegram."""
    try:
        http.post(_api("setMyCommands"), json={"commands": registry.telegram_menu()})
    except Exception as exc:  # noqa: BLE001
        logger.warning("setMyCommands failed", extra={"extra_fields": {"error": str(exc)[:200]}})


def _summary_text(db, range_name: str) -> str:
    """Format the GitHub activity summary for a named range (today/week/month).

    Shows the owner's own actions first (when ``github_owner_login`` is set),
    then the overall activity across every watched repo — activity the owner
    is involved in but that isn't only theirs.
    """
    start, end = compute_range(range_name, settings.display_timezone)
    a = github_summary(db, start, end, settings.github_owner_login)

    lines = [f"📊 {range_name.capitalize()} ({settings.display_timezone})"]

    mine = a.get("mine")
    if mine is not None:
        lines += [
            "",
            f"👤 *Mening harakatlarim* (@{a['owner_login']}):",
            f"Commits: {mine['commits']} · PR: {mine['pull_requests']} · "
            f"Issues: {mine['issues']} · Jami: {mine['total_events']}",
        ]

    lines += [
        "",
        "🌐 *Umumiy* (barcha repolar):",
        f"Commits: {a['commits']}",
        f"Hodisalar: {a['total_events']}",
        f"Pull requests: {a['pull_requests']}",
        f"Issues: {a['issues']}",
        f"👤 Odam: {a['human_events']} · 🤖 Avtomatika: {a['automation_events']}",
    ]

    # Who did what — only inside this range, so old commits never leak in.
    actors = list((a.get("by_actor") or {}).items())[:6]
    if actors:
        lines += ["", "👥 *Kim nima qildi:*"]
        lines += [f"• {login} — {n}" for login, n in actors]
    recent = _events_in_range(db, start, end, 5)
    if recent:
        fmt = "%H:%M" if range_name == "today" else "%d-%b %H:%M"
        lines += ["", "🕒 *Oxirgi harakatlar:*"]
        lines += [
            f"• {_local_time(e.created_at, fmt)} {e.actor_login}: {e.title} — {e.repo_full_name}"
            for e in recent
        ]

    if mine is None:
        lines += [
            "",
            "ℹ️ Shaxsiy harakatlaringizni ajratish uchun .env'da "
            "GITHUB_OWNER_LOGIN ni yozing.",
        ]

    return "\n".join(lines)


def _local_time(ts: dt.datetime, fmt: str) -> str:
    """Format a stored UTC timestamp in the display timezone."""
    if ts.tzinfo is None:  # SQLite returns naive datetimes; they are UTC
        ts = ts.replace(tzinfo=dt.timezone.utc)
    try:
        tz = ZoneInfo(settings.display_timezone)
    except Exception:  # noqa: BLE001 - unknown tz falls back to UTC
        tz = ZoneInfo("UTC")
    return ts.astimezone(tz).strftime(fmt)


def _events_in_range(db, start: dt.datetime, end: dt.datetime, limit: int) -> list:
    """Newest-first events whose time falls inside [start, end)."""
    return (
        db.query(GitHubEvent)
        .filter(GitHubEvent.created_at >= start, GitHubEvent.created_at < end)
        .order_by(GitHubEvent.created_at.desc())
        .limit(limit)
        .all()
    )


_RANGE_WORDS = {
    "today": "today", "bugun": "today",
    "week": "week", "hafta": "week",
    "month": "month", "oy": "month",
    "all": "all", "hammasi": "all",
}


def _events_text(db, range_name: str = "today", limit: int = 8) -> str:
    """Format GitHub events with who did what, limited to a time range.

    Defaults to today so old commits don't show up as if they were new.
    ``range_name="all"`` returns the latest events regardless of date.
    """
    if range_name == "all":
        events = (
            db.query(GitHubEvent).order_by(GitHubEvent.created_at.desc()).limit(limit).all()
        )
        if not events:
            return "Hali hodisa yo'q. Repo qo'shib, poll qiling."
        lines = ["🔔 Oxirgi hodisalar (sanadan qat'i nazar):"]
        fmt = "%d-%b %H:%M"
    else:
        start, end = compute_range(range_name, settings.display_timezone)
        events = _events_in_range(db, start, end, limit)
        if not events:
            return f"🔔 {range_name.capitalize()}: hodisa yo'q."
        lines = [f"🔔 Hodisalar — {range_name} ({settings.display_timezone}):"]
        fmt = "%H:%M" if range_name == "today" else "%d-%b %H:%M"
    for e in events:
        lines.append(
            f"• {_local_time(e.created_at, fmt)} {e.actor_login} {e.title} — {e.repo_full_name}"
        )
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
    read = reading.handle_reading(db, provider, t)  # /read /summary /topic ... (also /word cap)
    if read is not None:
        return read
    studied = study.handle_study(db, provider, t)  # /word /learned /quiz ... or a quiz answer
    if studied is not None:
        return studied
    if low == "/today":
        return _summary_text(db, "today")
    if low in ("/week", "/stats"):
        return _summary_text(db, "week")
    if low == "/month":
        return _summary_text(db, "month")
    parts = low.split()
    if parts and parts[0] in ("/github", "/events"):
        word = parts[1] if len(parts) > 1 else "today"
        if word not in _RANGE_WORDS:
            return "Foydalanish: /github [today|week|month|all]"
        return _events_text(db, _RANGE_WORDS[word])
    if low == "/repos":
        return _repos_text(db)
    if low == "/jira":
        return _jira_text()
    if low.split()[:1] == ["/news"]:
        arg = low.split()[1] if len(low.split()) > 1 else "tech"
        return _news_text("space" if arg in ("space", "kosmos") else "tech")
    if low == "/channels":
        return _channels_text()
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


def handle_message(db, provider, text: str, history: list[dict] | None = None) -> Reply:
    """What the owner sees for a message: text plus buttons.

    Wraps :func:`handle_text` (which stays the one-message router) and adds
    the guided flows, the menu screens, empty-state buttons and the single
    best next action under every reply.
    """
    t = (text or "").strip()
    if t == MENU_BUTTON_TEXT or t.lower() in ("start", "help", "menu"):
        t = "/menu"

    if t.startswith("/"):
        cmd = t.split()[0].lower().split("@")[0]
        if cmd == "/cancel":
            had = bot_state.clear_state(db)
            return Reply(
                "❌ Bekor qilindi." if had else "Bekor qilinadigan narsa yo'q.",
                [[do("🏠 Menyu", "/menu")]],
            )
        bot_state.clear_state(db)  # a new command drops any pending question
        if cmd in ("/start", "/menu", "/help"):
            return views.main_menu(db)
        if cmd == "/more":
            return views.more_screen()
        if cmd == "/bugun":
            return views.today_view(db)
        if cmd == "/photo":
            return views.photo_help()
        if cmd == "/diary" and len(t.split()) == 1:
            return views.diary_checklist(db)
        paper_reply = paper_flow.command(db, cmd, t)  # /date, /delete_entry
        if paper_reply is not None:
            return paper_reply.with_next(views.best_next(db, skip=cmd))
        if len(t.split()) == 1:  # bare command: ask one question
            started = flows.start(db, cmd)
            if started is not None:
                return started
        body = handle_text(db, provider, t, history)
        reply = Reply(body).with_next(views.empty_state_button(cmd, body))
        return reply.with_next(views.best_next(db, skip=cmd))

    st = bot_state.get_state(db)
    if st and st[0].startswith("paper:"):  # answering a paper-diary question
        return paper_flow.answer(db, st, t).with_next(views.best_next(db))

    pending = flows.pending_command(db)
    if pending:
        reply = flows.answer(db, pending, t, lambda line: handle_text(db, provider, line, history))
        return reply.with_next(views.best_next(db, skip=pending))
    return Reply(handle_text(db, provider, t, history)).with_next(views.best_next(db))


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


def _news_text(topic: str = "tech") -> str:
    """/news — the latest headlines from the configured tech news feeds.

    Feed failures are handled inside fetch_news, so this only needs to format
    the result. Returns a friendly message if news is disabled.
    """
    from ..integrations.news import fetch_news, format_news

    if not settings.news_enabled:
        return "🌍 Yangiliklar o'chirilgan (NEWS_ENABLED=false)."
    try:
        items = fetch_news(limit=8, topic=topic)
    except Exception as exc:  # noqa: BLE001
        logger.warning("news fetch failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return "🌍 Yangiliklarni olib bo'lmadi. Keyinroq urinib ko'ring."
    title = "🚀 *Kosmos yangiliklari*" if topic == "space" else "🌍 *Texnologiya yangiliklari*"
    return format_news(items, title)


def _channels_text() -> str:
    """/channels — list the public Telegram channels being watched, with the
    keywords that decide what gets forwarded."""
    from ..integrations.channels import keywords, watched_channels

    chans = watched_channels()
    if not chans:
        return (
            "📣 Hech qanday kanal kuzatilmayapti.\n\n"
            ".env'ga qo'shing (ommaviy kanal username'lari, @siz):\n"
            "WATCH_CHANNELS=kanal1,kanal2"
        )
    lines = ["📣 *Kuzatilayotgan kanallar:*"]
    lines += [f"• @{c}" for c in chans]
    lines += ["", "Faqat shu kalit so'zlar bo'lgan postlar yuboriladi:", ", ".join(keywords())]
    return "\n".join(lines)


def _jira_text() -> str:
    """/jira — list the Jira issues assigned to the owner (read-only).

    Guides the user to configure credentials when Jira isn't set up, and
    reports network/auth errors as a friendly message instead of crashing.
    """
    from ..integrations.jira import fetch_my_issues, format_issues, is_configured

    if not is_configured():
        return (
            "📋 Jira hali ulanmagan.\n\n"
            ".env'ga qo'shing:\n"
            "JIRA_BASE_URL=https://sayt.atlassian.net\n"
            "JIRA_EMAIL=email@example.com\n"
            "JIRA_API_TOKEN=<token>\n\n"
            "Token: id.atlassian.com/manage-profile/security/api-tokens"
        )
    try:
        issues = fetch_my_issues()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jira fetch failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return "📋 Jira ma'lumotini olib bo'lmadi. Token yoki URL ni tekshiring."
    return format_issues(issues)


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


MAX_PHOTO_BYTES = 10_000_000
_DOC_SUFFIX = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _photo_of(msg: dict) -> tuple[str, str] | None:
    """(file_id, suffix) of the photo in a message, or None. Telegram sends a
    photo in several sizes; the largest is used. Images sent as a file count too."""
    sizes = msg.get("photo")
    if sizes:
        best = max(sizes, key=lambda p: p.get("file_size") or (p.get("width", 0) * p.get("height", 0)))
        return best["file_id"], ".jpg"
    doc = msg.get("document") or {}
    if doc.get("mime_type") in _DOC_SUFFIX:
        return doc["file_id"], _DOC_SUFFIX[doc["mime_type"]]
    return None


def _download_file(http: httpx.Client, file_id: str) -> bytes:
    """Download a file the owner sent (size-limited)."""
    info = http.get(_api("getFile"), params={"file_id": file_id}).json()["result"]
    if (info.get("file_size") or 0) > MAX_PHOTO_BYTES:
        raise ValueError("file too large")
    resp = http.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{info['file_path']}")
    data = resp.content
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("file too large")
    return data


def _handle_owner_photo(http, session_local, provider, chat_id: Any, msg: dict, photo: tuple[str, str]) -> None:
    """Paper diary: download the photo, let the bot read it, show what it understood."""
    file_id, suffix = photo
    send_message(http, chat_id, "📷 Rasm qabul qilindi, o'qiyapman… (bir necha soniya)")
    try:
        data = _download_file(http, file_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("photo download failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        send_message(http, chat_id, "Rasmni yuklab bo'lmadi (10 MB dan kichik bo'lsin). Qayta yuboring.")
        return
    with session_local() as db:
        bot_state.clear_state(db)
        reply = paper_flow.handle_photo(db, provider, data, msg.get("caption") or "", suffix)
        reply.with_next(views.best_next(db, skip="/photo"))
    send_message(http, chat_id, reply.text, reply_markup=reply.markup())


def _handle_owner_text(http, session_local, provider, chat_id: Any, text: str) -> None:
    """Run one owner message (typed, or a ``do:`` button) and send the answer."""
    parts = text.strip().lower().split()
    cmd = parts[0] if parts else ""

    if cmd == "/start":  # set the persistent menu button, then show the menu
        send_message(http, chat_id, "👋 Salom! Pastdagi 🏠 Menyu tugmasi har doim shu yerda.",
                     reply_markup=MAIN_KEYBOARD)

    if cmd == "/review":
        with session_local() as db:
            bot_state.clear_state(db)
            send_review_card(http, chat_id, db)
        return

    if cmd == "/news":
        # News goes out as separate photo cards, not one text reply.
        with session_local() as db:
            bot_state.clear_state(db)
        topic = "space" if len(parts) > 1 and parts[1] in ("space", "kosmos") else "tech"
        if not settings.news_enabled:
            send_message(http, chat_id, _news_text(topic))
            return
        heading = "🚀 Kosmos yangiliklari" if topic == "space" else "🌍 Texnologiya yangiliklari"
        try:
            send_news_cards(http, chat_id, limit=5, heading=heading, topic=topic)
        except Exception as exc:  # noqa: BLE001
            logger.warning("news cards failed", extra={"extra_fields": {"error": str(exc)[:200]}})
            send_message(http, chat_id, "🌍 Yangiliklarni olib bo'lmadi. Keyinroq urinib ko'ring.")
        return

    with session_local() as db:
        reply = handle_message(db, provider, text)
    send_message(http, chat_id, reply.text, reply_markup=reply.markup())


def process_update(http, session_local, provider, update: dict) -> None:
    """Handle one Telegram update: reject non-owner chats, then route button
    taps and text through the bot's guided-conversation layer."""
    if update.get("callback_query"):
        process_callback(http, session_local, update["callback_query"], provider)
        return

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
    photo = _photo_of(msg) if "message" in update else None  # edits don't re-send photos
    if photo is not None:
        _handle_owner_photo(http, session_local, provider, chat_id, msg, photo)
        return
    if not text:
        return
    _handle_owner_text(http, session_local, provider, chat_id, text)


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
