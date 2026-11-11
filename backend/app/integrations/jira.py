"""Jira Cloud issues (READ-ONLY) for the owner's /jira command.

Lists the issues assigned to the authenticated user via the Jira Cloud REST
API. It never creates, edits, transitions or deletes anything — purely a view,
in the same spirit as /today and /github.

Auth is HTTP Basic with your Atlassian account email and an API token, both
read from .env (JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN). The token is a
secret and is never printed or sent anywhere except Jira itself.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

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


def is_configured() -> bool:
    """True when all three Jira credentials are present."""
    return bool(settings.jira_base_url and settings.jira_email and settings.jira_api_token)


def fetch_my_issues(http: httpx.Client | None = None, limit: int = 15) -> list[JiraIssue]:
    """Return the open issues assigned to the authenticated user.

    Raises RuntimeError when Jira isn't configured, and propagates HTTP errors
    for the caller to turn into a friendly message.
    """
    if not is_configured():
        raise RuntimeError("Jira not configured")

    base = settings.jira_base_url.rstrip("/")
    url = f"{base}{_SEARCH_PATH}"
    body = {"jql": _JQL, "maxResults": limit, "fields": _FIELDS}

    own = http is None
    client = http or httpx.Client(timeout=20)
    try:
        resp = client.post(
            url,
            json=body,
            auth=(settings.jira_email, settings.jira_api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        raw = (resp.json() or {}).get("issues") or []
    finally:
        if own:
            client.close()

    issues: list[JiraIssue] = []
    for it in raw:
        f = it.get("fields") or {}
        status = f.get("status") or {}
        cat = (status.get("statusCategory") or {}).get("key") or ""
        priority = (f.get("priority") or {}).get("name")
        key = it.get("key", "?")
        issues.append(
            JiraIssue(
                key=key,
                summary=f.get("summary") or "(sarlavhasiz)",
                status=status.get("name") or "—",
                status_category=cat,
                due=f.get("duedate"),
                priority=priority,
                url=f"{base}/browse/{key}",
            )
        )
    return issues


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
