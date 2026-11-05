"""Poll watched repositories, de-duplicate, store, and notify."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ...models.github import GitHubEvent, GitHubRepo
from ...redaction import redact
from .actors import classify_actor
from .client import GitHubClient
from .summarize import summarize_event

logger = logging.getLogger("lifeos.github.poller")


class SupportsNotify(Protocol):
    def notify_github_event(self, db: Session, event: GitHubEvent) -> None: ...


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(value: str | None) -> dt.datetime:
    if not value:
        return _utcnow()
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _existing_ids(db: Session, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return {
        row[0]
        for row in db.query(GitHubEvent.gh_id).filter(GitHubEvent.gh_id.in_(ids)).all()
    }


def _ingest_events(
    db: Session, repo: GitHubRepo, events: list[dict], notifier: SupportsNotify | None
) -> int:
    existing = _existing_ids(db, [str(e.get("id")) for e in events])
    new_count = 0
    for ev in reversed(events):  # oldest first
        gh_id = str(ev.get("id"))
        if gh_id in existing:
            continue
        s = summarize_event(ev)
        actor = ev.get("actor") or {}
        login = actor.get("login", "")
        obj = GitHubEvent(
            gh_id=gh_id,
            repo_full_name=repo.full_name,
            type=ev.get("type", "") or "",
            action=s["action"],
            actor_login=login,
            actor_type=classify_actor(login, actor.get("type")),
            branch=s["branch"],
            number=s["number"],
            title=s["title"],
            summary=s["summary"],
            url=s["url"],
            created_at=_parse_iso(ev.get("created_at")),
            ingested_at=_utcnow(),
            raw=redact(ev),
        )
        db.add(obj)
        existing.add(gh_id)
        new_count += 1
        if notifier is not None:
            notifier.notify_github_event(db, obj)
    return new_count


def _ingest_commits(
    db: Session, repo: GitHubRepo, commits: list[dict], notifier: SupportsNotify | None
) -> int:
    existing = _existing_ids(db, [f"commit:{c.get('sha')}" for c in commits])
    new_count = 0
    for c in reversed(commits):  # oldest first
        sha = c.get("sha") or ""
        gh_id = f"commit:{sha}"
        if not sha or gh_id in existing:
            continue
        commit = c.get("commit") or {}
        commit_author = commit.get("author") or {}
        gh_author = c.get("author") or {}
        login = gh_author.get("login") or commit_author.get("name") or "unknown"
        message = (commit.get("message") or "").splitlines()[0] if commit.get("message") else ""
        obj = GitHubEvent(
            gh_id=gh_id,
            repo_full_name=repo.full_name,
            type="Commit",
            action=None,
            actor_login=login,
            actor_type=classify_actor(gh_author.get("login") or login, gh_author.get("type")),
            branch=None,
            number=None,
            title=f"committed {sha[:7]}",
            summary=message or None,
            url=c.get("html_url"),
            created_at=_parse_iso(commit_author.get("date")),
            ingested_at=_utcnow(),
            raw=redact(c),
        )
        db.add(obj)
        existing.add(gh_id)
        new_count += 1
        if notifier is not None:
            notifier.notify_github_event(db, obj)
    return new_count


def poll_repo(
    db: Session,
    client: GitHubClient,
    repo: GitHubRepo,
    notifier: SupportsNotify | None = None,
) -> int:
    """Poll one repository (events feed + commits). Returns NEW items stored."""
    repo.last_polled_at = _utcnow()
    new_count = 0

    # 1) Events feed (pushes, PRs, issues, ...) — great for public repos.
    events, new_etag = client.repo_events(repo.full_name, repo.etag)
    if events is not None:  # None == 304 Not Modified
        repo.etag = new_etag
        new_count += _ingest_events(db, repo, events, notifier)

    # 2) Commits directly — reliable for private repos and has no feed delay.
    try:
        commits = client.repo_commits(repo.full_name)
        new_count += _ingest_commits(db, repo, commits, notifier)
    except Exception as exc:  # noqa: BLE001 - commits are best-effort
        logger.warning(
            "github commits fetch failed",
            extra={"extra_fields": {"repo": repo.full_name, "error": str(exc)[:200]}},
        )

    db.commit()
    if new_count:
        logger.info(
            "github poll stored items",
            extra={"extra_fields": {"repo": repo.full_name, "new_items": new_count}},
        )
    return new_count


def poll_all(
    db: Session, client: GitHubClient, notifier: SupportsNotify | None = None
) -> dict[str, int]:
    """Poll every active repo. Per-repo errors are logged and skipped."""
    results: dict[str, int] = {}
    repos = db.query(GitHubRepo).filter(GitHubRepo.active.is_(True)).all()
    for repo in repos:
        try:
            results[repo.full_name] = poll_repo(db, client, repo, notifier)
        except Exception as exc:  # noqa: BLE001 - one bad repo must not stop others
            db.rollback()
            logger.warning(
                "github poll failed",
                extra={"extra_fields": {"repo": repo.full_name, "error": str(exc)[:200]}},
            )
            results[repo.full_name] = -1
    return results
