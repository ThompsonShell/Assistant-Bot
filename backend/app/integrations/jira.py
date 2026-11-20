"""Jira Cloud for the bot: list my issues, check the connection, create a task.

Auth is HTTP Basic with the Atlassian account email and an API token, all read
from .env (JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN). The token is a secret:
it is only sent to Jira and never printed or logged.

The bot reads freely. It **creates** issues only after the owner presses
"Yaratish" on a preview (see app/bot/jira_flow.py); it never edits, moves or
deletes anything.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.jira")

# Enhanced search endpoint (the legacy /rest/api/3/search is being retired).
_SEARCH_PATH = "/rest/api/3/search/jql"

# My open issues, soonest due and highest priority first.
_JQL = (
    "assignee = currentUser() AND statusCategory != Done "
    "ORDER BY duedate ASC, priority DESC"
)

_FIELDS = ["summary", "status", "duedate", "priority"]


class JiraError(Exception):
    """A Jira call failed; ``user_message`` is safe and useful to show (Uzbek)."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


# ── configuration ─────────────────────────────────────────────────────

def _clean(value: str | None) -> str:
    return (value or "").strip().strip("'\"").strip()


def missing_settings() -> list[str]:
    """Names (never values) of the JIRA_* settings that are empty."""
    wanted = [
        ("JIRA_BASE_URL", settings.jira_base_url),
        ("JIRA_EMAIL", settings.jira_email),
        ("JIRA_API_TOKEN", settings.jira_api_token),
    ]
    return [name for name, value in wanted if not _clean(value)]


def is_configured() -> bool:
    """True when all three Jira credentials are present."""
    return not missing_settings()


def base_url() -> str:
    """The site URL from JIRA_BASE_URL, tolerant of a missing https:// or a
    pasted path (https://site.atlassian.net/jira/... -> https://site.atlassian.net)."""
    raw = _clean(settings.jira_base_url)
    if not raw:
        raise JiraError("JIRA_BASE_URL bo'sh.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlparse(raw)
    return f"{parts.scheme}://{parts.netloc}"


def project_key_from_env() -> str | None:
    return _clean(settings.jira_project_key).upper() or None


# ── one place that talks to Jira ──────────────────────────────────────

def _explain(resp: httpx.Response) -> str:
    """Turn a Jira error response into one clear Uzbek sentence."""
    status = resp.status_code
    detail = ""
    try:
        body = resp.json()
        msgs = list(body.get("errorMessages") or []) + [f"{k}: {v}" for k, v in (body.get("errors") or {}).items()]
        detail = "; ".join(str(m) for m in msgs)[:200]
    except ValueError:
        pass
    if status == 401:
        return "Jira kirishni rad etdi (401). JIRA_EMAIL yoki JIRA_API_TOKEN noto'g'ri. Tokenni id.atlassian.com dan qayta yarating."
    if status == 403:
        return "Jira ruxsat bermadi (403). Bu hisobda shu loyihada ruxsat yo'q."
    if status == 404:
        return "Jira topa olmadi (404). JIRA_BASE_URL yoki loyiha kaliti noto'g'ri."
    if status == 400:
        return f"Jira so'rovni qabul qilmadi: {detail or 'noto‘g‘ri maydon'}"
    return f"Jira xatosi ({status}). {detail}".strip()


def _request(method: str, path: str, *, http: httpx.Client | None = None, **kwargs) -> dict:
    """Call the Jira REST API with the configured credentials."""
    if not is_configured():
        raise JiraError("Jira sozlanmagan: " + ", ".join(missing_settings()) + " yo'q.")
    url = base_url() + path
    headers = {"Accept": "application/json", **(kwargs.pop("headers", None) or {})}
    own = http is None
    client = http or httpx.Client(timeout=20)
    try:
        resp = client.request(
            method, url,
            auth=(_clean(settings.jira_email), _clean(settings.jira_api_token)),
            headers=headers,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise JiraError(f"Jira'ga ulanib bo'lmadi: {type(exc).__name__}. JIRA_BASE_URL va internetni tekshiring.") from exc
    finally:
        if own:
            client.close()
    if resp.status_code >= 400:
        raise JiraError(_explain(resp))
    try:
        return resp.json() if resp.content else {}
    except ValueError as exc:
        raise JiraError("Jira javobi noto'g'ri (JSON emas). JIRA_BASE_URL aniq saytingiznikimi?") from exc


# ── reading ───────────────────────────────────────────────────────────

@dataclass
class JiraIssue:
    key: str                 # e.g. "PROJ-12"
    summary: str
    status: str              # e.g. "In Progress"
    status_category: str     # "new" | "indeterminate" | "done"
    due: str | None          # ISO date or None
    priority: str | None
    url: str

    @property
    def marker(self) -> str:
        return {"new": "⚪️", "indeterminate": "🟡", "done": "✅"}.get(
            self.status_category, "▫️"
        )

    @property
    def is_overdue(self) -> bool:
        if not self.due:
            return False
        try:
            return dt.date.fromisoformat(self.due) < dt.date.today()
        except ValueError:
            return False


def fetch_my_issues(http: httpx.Client | None = None, limit: int = 15) -> list[JiraIssue]:
    """Open issues assigned to the authenticated user."""
    data = _request(
        "POST", _SEARCH_PATH, http=http,
        json={"jql": _JQL, "maxResults": limit, "fields": _FIELDS},
        headers={"Content-Type": "application/json"},
    )
    base = base_url()
    issues: list[JiraIssue] = []
    for it in data.get("issues") or []:
        f = it.get("fields") or {}
        status = f.get("status") or {}
        key = it.get("key", "?")
        issues.append(
            JiraIssue(
                key=key,
                summary=f.get("summary") or "(sarlavhasiz)",
                status=status.get("name") or "—",
                status_category=(status.get("statusCategory") or {}).get("key") or "",
                due=f.get("duedate"),
                priority=(f.get("priority") or {}).get("name"),
                url=f"{base}/browse/{key}",
            )
        )
    return issues


def whoami(http: httpx.Client | None = None) -> dict:
    """Who the token belongs to (proves the connection works)."""
    return _request("GET", "/rest/api/3/myself", http=http)


def list_projects(http: httpx.Client | None = None, limit: int = 30) -> list[dict]:
    """Projects this account can see: [{"key": "PROJ", "name": "..."}]."""
    data = _request("GET", "/rest/api/3/project/search", http=http,
                    params={"maxResults": limit, "orderBy": "name"})
    return [{"key": p["key"], "name": p.get("name", p["key"])} for p in data.get("values") or []]


# ── creating ──────────────────────────────────────────────────────────

@dataclass
class CreatedIssue:
    key: str
    url: str


def pick_issue_type(project_key: str, http: httpx.Client | None = None) -> str:
    """JIRA_ISSUE_TYPE (default Task) if the project has it, else the first
    ordinary (non-subtask) type."""
    data = _request("GET", f"/rest/api/3/project/{project_key}", http=http)
    types = [t for t in data.get("issueTypes") or [] if not t.get("subtask")]
    if not types:
        raise JiraError(f"{project_key} loyihasida oddiy issue turi topilmadi.")
    wanted = (_clean(settings.jira_issue_type) or "Task").lower()
    for t in types:
        if t.get("name", "").lower() == wanted:
            return t["name"]
    return types[0]["name"]


def _adf(text: str) -> dict:
    """Plain text as an Atlassian Document Format body (required by API v3)."""
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def create_issue(
    project_key: str,
    summary: str,
    *,
    due: dt.date | None = None,
    labels: list[str] | None = None,
    description: str | None = None,
    http: httpx.Client | None = None,
) -> CreatedIssue:
    """Create one issue. Raises JiraError with a readable reason on failure."""
    fields: dict = {
        "project": {"key": project_key},
        "summary": summary.strip()[:255],
        "issuetype": {"name": pick_issue_type(project_key, http)},
    }
    if description:
        fields["description"] = _adf(description)
    if due:
        fields["duedate"] = due.isoformat()
    if labels:
        fields["labels"] = labels
    data = _request("POST", "/rest/api/3/issue", http=http, json={"fields": fields},
                    headers={"Content-Type": "application/json"})
    key = data.get("key")
    if not key:
        raise JiraError("Jira issue yaratdi, lekin kalitini qaytarmadi.")
    return CreatedIssue(key=key, url=f"{base_url()}/browse/{key}")


# ── text ──────────────────────────────────────────────────────────────

def _fmt_due(issue: JiraIssue) -> str:
    if not issue.due:
        return "muddatsiz"
    try:
        d = dt.date.fromisoformat(issue.due).strftime("%d-%b")
    except ValueError:
        d = issue.due
    return ("⚠️ " if issue.is_overdue else "⏰ ") + d


def format_issues(issues: list[JiraIssue]) -> str:
    """Render the issue list as a Telegram message."""
    if not issues:
        return "📋 *Jira* — ochiq issue yo'q. 🎉"
    lines = ["📋 *Jira — mening issue'larim:*", ""]
    for it in issues:
        prio = f" · {it.priority}" if it.priority else ""
        lines.append(f"{it.marker} *{it.key}* {it.summary}")
        lines.append(f"   {it.status} · {_fmt_due(it)}{prio}")
    return "\n".join(lines)
