"""Creating a Jira task from Telegram: "/jira add <title>" or plain words like
"Jira ga task qo'sh: testlar yozish".

Always a preview first: the bot shows project, type, title and due date and
creates the issue only when the owner presses "Yaratish". Nothing else in Jira
is ever changed.

State: ``jira:title`` (waiting for a title), ``jira:confirm`` (preview shown).
Buttons: ``jc:ok`` create, ``jc:proj`` change project, ``jp:<KEY>`` pick one.
"""
from __future__ import annotations

import datetime as dt
import re

from ..config import settings
from ..integrations import jira
from ..study import reading, service as study
from . import runtime, state
from .ui import Reply, do

CANCEL = ("❌ Bekor qilish", "do:/cancel")
_KV_PROJECT = "jira_project"


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


_NORMAL = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'"})
_VERB = re.compile(r"(qo'sh|qosh|yarat|kirit|add\b|create\b|new task)", re.IGNORECASE)


def intent(text: str) -> str | None:
    """Does a plain message ask to add a Jira task? Returns the task text after
    the colon ("" when there is none, so the bot asks), or None if it is not
    such a request."""
    t = (text or "").translate(_NORMAL)
    if t.lstrip().startswith("/") or "?" in t or not re.search(r"\bjira", t, re.IGNORECASE):
        return None
    head, sep, tail = t.partition(":")
    if not _VERB.search(head) or not re.search(r"task|vazifa|issue|ticket|topshiriq", head, re.IGNORECASE):
        return None
    return tail.strip() if sep else ""


# ── project ───────────────────────────────────────────────────────────

def current_project(db) -> str | None:
    return jira.project_key_from_env() or (reading.get_kv(db, _KV_PROJECT) or None)


def _project_chosen(db, pending: dict, key: str) -> Reply:
    """A project is known: continue the pending task, or just confirm the choice."""
    reading.set_kv(db, _KV_PROJECT, key)
    if pending.get("title"):
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

def start(db, title: str, due: dt.date | None, labels: list[str]) -> Reply:
    """Begin a creation: configured? project known? then show the preview."""
    if not jira.is_configured():
        return not_configured()
    pending = {"title": title, "due": due.isoformat() if due else None, "labels": labels}
    project = current_project(db)
    if not project:
        return _project_picker(db, pending)
    return preview(db, {**pending, "project": project})


def preview(db, pending: dict) -> Reply:
    state.set_state(db, "jira:confirm", pending)
    lines = [
        "📋 Jira'da yangi task yaratilsinmi?",
        "",
        f"🗂 Loyiha: {pending['project']}",
        f"📝 Nom: {pending['title']}",
    ]
    if pending.get("due"):
        lines.append(f"⏰ Muddat: {pending['due']}")
    if pending.get("labels"):
        lines.append("🏷 Teglar: " + ", ".join(pending["labels"]))
    lines += ["", "Boshqa nom yozsangiz, nom almashadi."]
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
    try:
        created = jira.create_issue(
            data["project"], data["title"],
            due=dt.date.fromisoformat(data["due"]) if data.get("due") else None,
            labels=data.get("labels") or None,
            description="Telegram bot orqali yaratildi.",
        )
    except jira.JiraError as exc:  # keep the preview so one tap retries
        return Reply(f"❌ Yaratilmadi: {exc.user_message}", [[("🔁 Qayta urinish", "jc:ok"), ("🔁 Loyiha", "jc:proj")], [CANCEL]])
    state.clear_state(db)
    return Reply(f"✅ Jira'da yaratildi: {created.key}\n{data['title']}\n{created.url}",
                 [[do("📋 Mening issue'larim", "/jira")]])


# ── commands, answers, buttons ────────────────────────────────────────

def from_text(db, task_text: str) -> Reply:
    """Start a task from the text after "add" or after the colon; ask for the
    title when there is none."""
    if not jira.is_configured():
        return not_configured()
    if not task_text.strip():
        state.set_state(db, "jira:title")
        return Reply("📝 Task nomi nima? Oxirida muddat (ertaga yoki 2026-11-25) va #teg yozishingiz mumkin.", [[CANCEL]])
    title, due, labels = parse_task(task_text)
    return start(db, title, due, labels) if title else Reply("Task nomini yozing.", [[CANCEL]])


def command(db, text: str) -> Reply | None:
    """/jira add <title>, /jira status, /jira project. None for a plain /jira."""
    parts = text.split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else ""
    rest = parts[2].strip() if len(parts) > 2 else ""
    if sub == "add":
        return from_text(db, rest)
    if sub == "status":
        return status()
    if sub == "project":
        if not jira.is_configured():
            return not_configured()
        return _project_picker(db, {"title": "", "due": None, "labels": []})
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
    """A typed message while the bot waits for a title or a changed title."""
    kind, data = st
    title, due, labels = parse_task(text)
    if not title:
        return Reply("Task nomini yozing.", [[CANCEL]])
    if kind == "jira:confirm":  # typing replaces the title, keeps project and date unless given
        merged = {**data, "title": title, "due": due.isoformat() if due else data.get("due")}
        merged["labels"] = labels or data.get("labels") or []
        return preview(db, merged)
    return start(db, title, due, labels)


def on_callback(db, parts: list[str]) -> Reply | None:
    """``jc:ok`` create, ``jc:proj`` change project, ``jp:<KEY>`` choose project."""
    if parts[0] == "jc" and len(parts) > 1:
        if parts[1] == "ok":
            return create(db)
        if parts[1] == "proj":
            st = state.get_state(db)
            pending = st[1] if st else {"title": "", "due": None, "labels": []}
            return _project_picker(db, {k: pending.get(k) for k in ("title", "due", "labels")})
    if parts[0] == "jp" and len(parts) > 1:
        st = state.get_state(db)
        pending = {k: (st[1].get(k) if st else None) for k in ("title", "due", "labels")}
        return _project_chosen(db, pending, parts[1].upper())
    return None
