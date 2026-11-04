"""Turn a raw GitHub Events API item into a human-readable summary."""
from __future__ import annotations

from typing import Any


def _first_line(text: str | None) -> str | None:
    if not text:
        return None
    return text.splitlines()[0]


def summarize_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Return {title, summary, branch, number, url, action} for an event."""
    etype = ev.get("type", "") or ""
    payload = ev.get("payload") or {}
    repo = (ev.get("repo") or {}).get("name", "")  # "owner/name"
    base = f"https://github.com/{repo}" if repo else "https://github.com"

    branch: str | None = None
    number: int | None = None
    url: str | None = base
    action: str | None = payload.get("action")
    summary: str | None = None
    title = etype

    if etype == "PushEvent":
        ref = payload.get("ref", "") or ""
        branch = ref.split("/", 2)[-1] if ref else None
        commits = payload.get("commits") or []
        n = payload.get("size", len(commits))
        title = f"pushed {n} commit{'s' if n != 1 else ''}" + (
            f" to {branch}" if branch else ""
        )
        msgs = [_first_line(c.get("message")) for c in commits[:5]]
        msgs = [m for m in msgs if m]
        summary = "\n".join(f"- {m}" for m in msgs) if msgs else None
        url = f"{base}/commits/{branch}" if branch else f"{base}/commits"

    elif etype == "PullRequestEvent":
        pr = payload.get("pull_request") or {}
        number = payload.get("number") or pr.get("number")
        if action == "closed" and pr.get("merged"):
            action = "merged"
        title = f"{action} pull request #{number}"
        summary = pr.get("title")
        branch = (pr.get("base") or {}).get("ref")
        url = pr.get("html_url") or f"{base}/pull/{number}"

    elif etype == "PullRequestReviewEvent":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        state = (payload.get("review") or {}).get("state")
        title = f"reviewed pull request #{number}"
        summary = state
        url = pr.get("html_url") or f"{base}/pull/{number}"

    elif etype == "IssuesEvent":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        title = f"{action} issue #{number}"
        summary = issue.get("title")
        url = issue.get("html_url") or f"{base}/issues/{number}"

    elif etype == "IssueCommentEvent":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        title = f"commented on #{number}"
        summary = issue.get("title")
        url = (payload.get("comment") or {}).get("html_url") or f"{base}/issues/{number}"

    elif etype == "CreateEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref")
        title = f"created {ref_type}" + (f" {ref}" if ref else "")
        if ref_type == "branch" and ref:
            branch = ref

    elif etype == "DeleteEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref")
        title = f"deleted {ref_type}" + (f" {ref}" if ref else "")

    elif etype == "ReleaseEvent":
        rel = payload.get("release") or {}
        title = f"{action} release {rel.get('tag_name', '')}".strip()
        url = rel.get("html_url") or f"{base}/releases"

    elif etype == "ForkEvent":
        title = "forked the repository"

    elif etype == "WatchEvent":
        title = "starred the repository"

    return {
        "title": title,
        "summary": summary,
        "branch": branch,
        "number": number,
        "url": url,
        "action": action,
    }
