"""Creating Jira tasks from Telegram.

Ways in:
  * ``/jira add <title>``, one task per line for several (also ``;``)
  * plain words: "Jira ga task qo'sh: testlar yozish", "Jira ga bugungi
    vazifalarni qo'sh" (that one sends the bot's own tasks, like /jira sync)
  * ``/jira sync``: today's open tasks from /tasks that were not sent yet

Always a preview first: the bot lists project, titles and due dates and creates
the issues only when the owner presses "Yaratish". Nothing else in Jira is ever
changed. A bot task that was sent is remembered (``jira_links``), so it is never
sent twice.

State: ``jira:title`` (waiting for a title), ``jira:confirm`` (preview shown),
``jira:project`` (choosing a project). The pending request is
``{"project", "items": [{"title", "due", "labels", "task_id"}]}``.
Buttons: ``jc:ok`` create, ``jc:proj`` change project, ``jp:<KEY>`` pick one.
"""
from __future__ import annotations

import datetime as dt
import re

from ..integrations import jira
from ..models.task import JiraLink, Task
from ..study import reading, service as study
from . import runtime, state
from .ui import Reply, do

CANCEL = ("❌ Bekor qilish", "do:/cancel")
_KV_PROJECT = "jira_project"
MAX_ITEMS = 10  # one request never creates more than this


# ── understanding the request ─────────────────────────────────────────

def parse_task(text: str) -> tuple[str, dt.date | None, list[str]]:
    """Split "write tests #study 2026-11-25" into (title, due date, labels).

    Understood at the end of the text: an ISO date, "ertaga" (tomorrow) or
    "bugun" (today). ``#word`` tokens become Jira labels.
    """
    today = study.local_today()
    title = " ".join((text or "").split())
    due: dt.date | None = None

    # Labels first, so "ertaga #study" still ends with the date word.
    labels = re.findall(r"#([\w-]+)", title)
    title = re.sub(r"\s*#[\w-]+", "", title).strip()

    m = re.search(r"(?:^|\s)(\d{4}-\d{2}-\d{2}|ertaga|bugun)\s*$", title, re.IGNORECASE)
    if m:
        word = m.group(1).lower()
        if word == "ertaga":
            due = today + dt.timedelta(days=1)
        elif word == "bugun":
            due = today
        else:
            try:
                due = dt.date.fromisoformat(word)
            except ValueError:
                due = None  # not a real date: leave it in the title
        if due is not None:
            title = title[: m.start(1)].strip()
    return title, due, labels


def parse_items(text: str) -> list[dict]:
    """One task per non-empty line (or per ';'). Returns at most MAX_ITEMS."""
    items = []
    for chunk in re.split(r"[\n;]+", text or ""):
        chunk = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", chunk).strip()   # "- a", "1. a", "2) a"
        title, due, labels = parse_task(chunk)
        if title:
            items.append({"title": title, "due": due.isoformat() if due else None,
                          "labels": labels, "task_id": None})
    return items[:MAX_ITEMS]


_NORMAL = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'"})
# Commands only ("qo'sh", "yubor"), not "qo'shgan edim" or "yuborganman": \b ends the word.
_VERB = re.compile(
    r"\b(qo'sh|qo'shib|qosh|yarat|yaratib|kirit|kiritib|yubor|yuborib|jo'nat|add|create|send|sync)\b",
    re.IGNORECASE,
)
# "bugungi vazifalarni", "barcha tasklarim", "rejamni" ... = the bot's own tasks, not a new title.
_OWN_TASKS = re.compile(r"bugungi|barcha|hamma|vazifalarim|tasklarim|rejam|vazifalarni|tasklarni", re.IGNORECASE)


def intent(text: str) -> tuple[str, str] | None:
    """Does a plain message ask to put tasks into Jira?

    Returns ("add", text after the colon or "" to ask), ("sync", "") when it
    means the bot's own tasks, or None when it is not such a request (questions,
    chat about Jira, commands).
    """
    t = (text or "").translate(_NORMAL)
    if t.lstrip().startswith("/") or "?" in t or not re.search(r"\bjira", t, re.IGNORECASE):
        return None
    head, sep, tail = t.partition(":")
    if not _VERB.search(head):
        return None
    if sep and tail.strip():
        return ("add", tail.strip())
    if _OWN_TASKS.search(head):
        return ("sync", "")
    return ("add", "")


# ── project ───────────────────────────────────────────────────────────

def current_project(db) -> str | None:
    return jira.project_key_from_env() or (reading.get_kv(db, _KV_PROJECT) or None)


def _project_chosen(db, pending: dict, key: str) -> Reply:
    """A project is known: continue the pending request, or just confirm the choice."""
    reading.set_kv(db, _KV_PROJECT, key)
    if pending.get("items"):
        return preview(db, {**pending, "project": key})
    state.clear_state(db)
    return Reply(f"🗂 Loyiha: {key}. Endi: /jira add <nom>", [[do("➕ Task qo'shish", "/jira add")]])


def _project_picker(db, pending: dict) -> Reply:
    try:
        projects = jira.list_projects()
    except jira.JiraError as exc:
        return Reply(f"📋 Loyihalarni olib bo'lmadi: {exc.user_message}\n\n"
                     "JIRA_PROJECT_KEY=KALIT ni .env ga yozing (masalan JIRA_PROJECT_KEY=PROJ).")
    if not projects:
        return Reply("📋 Bu hisobda ko'rinadigan loyiha yo'q. Jira'da loyiha yarating yoki ruxsat so'rang.")
    if len(projects) == 1:
        return _project_chosen(db, pending, projects[0]["key"])
    state.set_state(db, "jira:project", pending)
    rows = [[(f"{p['key']} — {p['name']}"[:40], f"jp:{p['key']}")] for p in projects[:10]]
    rows.append([CANCEL])
    return Reply("📋 Qaysi loyihaga yaratamiz? (tanlov eslab qolinadi)", rows)


# ── preview and create ────────────────────────────────────────────────

def start(db, items: list[dict]) -> Reply:
    """Begin a request: configured? project known? then show the preview."""
    if not jira.is_configured():
        return not_configured()
    pending = {"items": items}
    project = current_project(db)
    if not project:
        return _project_picker(db, pending)
    return preview(db, {**pending, "project": project})


def preview(db, pending: dict) -> Reply:
    state.set_state(db, "jira:confirm", pending)
    items = pending["items"]
    lines = [
        f"📋 Jira'da {len(items)} ta task yaratilsinmi?" if len(items) > 1 else "📋 Jira'da yangi task yaratilsinmi?",
        "",
        f"🗂 Loyiha: {pending['project']}",
    ]
    for i, it in enumerate(items, 1):
        extra = (f" · ⏰ {it['due']}" if it.get("due") else "") + (
            " · 🏷 " + ", ".join(it["labels"]) if it.get("labels") else "")
        lines.append(f"{i}. {it['title']}{extra}" if len(items) > 1 else f"📝 Nom: {it['title']}{extra}")
    lines += ["", "Boshqa matn yozsangiz, ro'yxat almashadi."]
    return Reply("\n".join(lines), [
        [("✅ Yaratish", "jc:ok"), ("🔁 Loyiha", "jc:proj")],
        [CANCEL],
    ])


def not_configured() -> Reply:
    missing = jira.missing_settings()
    return Reply(
        "📋 Jira ulanmagan.\n"
        f"Yetishmayotgan sozlamalar: {', '.join(missing)}\n\n"
        "Ularni Assistant-Bot/.env fayliga yozing (boshqa loyihaning .env fayliga emas), "
        "so'ng botni qayta ishga tushiring: ./scripts/run-local.sh\n\n"
        "Token: id.atlassian.com/manage-profile/security/api-tokens\n\n"
        "Sozlama bor-u, baribir shu xabar chiqsa: ./scripts/check-jira.sh\n" + runtime.footer(),
        [[do("🏠 Menyu", "/menu")]],
    )


def create(db) -> Reply:
    st = state.get_state(db)
    if not st or st[0] != "jira:confirm":
        return Reply("Bu so'rov eskirgan. Qayta yuboring: /jira add <nom>", [[do("➕ Task qo'shish", "/jira add")]])
    data = st[1]
    created: list[tuple[dict, jira.CreatedIssue]] = []
    failed: list[tuple[dict, str]] = []
    for item in data["items"]:
        try:
            issue = jira.create_issue(
                data["project"], item["title"],
                due=dt.date.fromisoformat(item["due"]) if item.get("due") else None,
                labels=item.get("labels") or None,
                description="Telegram bot orqali yaratildi.",
            )
        except jira.JiraError as exc:
            failed.append((item, exc.user_message))
            continue
        created.append((item, issue))
        if item.get("task_id"):  # remember it, so /jira sync never sends it again
            db.merge(JiraLink(task_id=item["task_id"], jira_key=issue.key))
            db.commit()

    lines = [f"✅ Jira'da yaratildi: {issue.key} — {item['title']}\n{issue.url}" for item, issue in created]
    if failed:
        # Keep only what failed, so one tap retries just those.
        state.set_state(db, "jira:confirm", {**data, "items": [item for item, _ in failed]})
        lines += [f"❌ Yaratilmadi: {item['title']}\n   {why}" for item, why in failed]
        return Reply("\n\n".join(lines), [[("🔁 Qayta urinish", "jc:ok"), ("🔁 Loyiha", "jc:proj")], [CANCEL]])
    state.clear_state(db)
    return Reply("\n\n".join(lines), [[do("📋 Mening issue'larim", "/jira")]])


# ── sending the bot's own tasks ───────────────────────────────────────

def sync(db) -> Reply:
    """Today's open bot tasks (and overdue or undated ones) that are not in Jira yet."""
    if not jira.is_configured():
        return not_configured()
    today = study.local_today()
    sent = {task_id for (task_id,) in db.query(JiraLink.task_id)}
    tasks = (
        db.query(Task)
        .filter(Task.status != "done")
        .filter((Task.scheduled_date <= today) | (Task.scheduled_date.is_(None)))
        .order_by(Task.scheduled_date.is_(None), Task.scheduled_date, Task.id)
        .all()
    )
    items = [
        {"title": t.title, "due": t.scheduled_date.isoformat() if t.scheduled_date else None,
         "labels": [], "task_id": t.id}
        for t in tasks if t.id not in sent
    ][:MAX_ITEMS]
    if not items:
        return Reply("📋 Jira'ga yuboriladigan vazifa yo'q (hammasi yuborilgan yoki hali reja yo'q).",
                     [[do("📅 Reja tuzish", "/plan"), do("📋 Vazifalar", "/tasks")]])
    return start(db, items)


# ── commands, answers, buttons ────────────────────────────────────────

def from_text(db, task_text: str) -> Reply:
    """Start from the text after "add" or after the colon; ask when there is none."""
    if not jira.is_configured():
        return not_configured()
    if not task_text.strip():
        state.set_state(db, "jira:title")
        return Reply("📝 Task nomi nima? Bir nechta bo'lsa, har birini yangi qatordan yozing.\n"
                     "Oxirida muddat (ertaga yoki 2026-11-25) va #teg yozishingiz mumkin.", [[CANCEL]])
    items = parse_items(task_text)
    return start(db, items) if items else Reply("Task nomini yozing.", [[CANCEL]])


def from_intent(db, request: tuple[str, str]) -> Reply:
    kind, text = request
    return sync(db) if kind == "sync" else from_text(db, text)


def command(db, text: str) -> Reply | None:
    """/jira add <title>, /jira sync, /jira status, /jira project. None for a plain /jira."""
    parts = text.split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else ""
    rest = parts[2].strip() if len(parts) > 2 else ""
    if sub == "add":
        return from_text(db, rest)
    if sub == "sync":
        return sync(db)
    if sub == "status":
        return status()
    if sub == "project":
        if not jira.is_configured():
            return not_configured()
        return _project_picker(db, {"items": []})
    return None


def status() -> Reply:
    """Prove the connection works, or say exactly what is wrong."""
    if not jira.is_configured():
        return not_configured()
    try:
        me = jira.whoami()
    except jira.JiraError as exc:
        return Reply(f"📋 Jira ulanmadi: {exc.user_message}", [[do("🏠 Menyu", "/menu")]])
    project = jira.project_key_from_env()
    return Reply(
        f"✅ Jira ulangan: {me.get('displayName', '?')}\n"
        f"🗂 Loyiha: {project or 'tanlanmagan (/jira add da so‘raladi)'}\n{runtime.footer()}",
        [[do("➕ Task qo'shish", "/jira add"), do("📋 Issue'lar", "/jira")]],
    )


def answer(db, st: tuple[str, dict], text: str) -> Reply:
    """A typed message while the bot waits for a title, or to replace the list in the preview."""
    kind, data = st
    items = parse_items(text)
    if not items:
        return Reply("Task nomini yozing.", [[CANCEL]])
    if kind == "jira:confirm":
        return preview(db, {**data, "items": items})
    return start(db, items)


def on_callback(db, parts: list[str]) -> Reply | None:
    """``jc:ok`` create, ``jc:proj`` change project, ``jp:<KEY>`` choose project."""
    if parts[0] == "jc" and len(parts) > 1:
        if parts[1] == "ok":
            return create(db)
        if parts[1] == "proj":
            st = state.get_state(db)
            return _project_picker(db, {"items": st[1].get("items", []) if st else []})
    if parts[0] == "jp" and len(parts) > 1:
        st = state.get_state(db)
        return _project_chosen(db, {"items": st[1].get("items", []) if st else []}, parts[1].upper())
    return None
