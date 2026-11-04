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


def poll_repo(
    db: Session,
    client: GitHubClient,
    repo: GitHubRepo,
    notifier: SupportsNotify | None = None,
) -> int:
    """Poll one repository. Returns the number of NEW events stored."""
    events, new_etag = client.repo_events(repo.full_name, repo.etag)
    repo.last_polled_at = _utcnow()

    if events is None:  # 304 Not Modified
        db.commit()
        return 0

    repo.etag = new_etag

    ids = [str(e.get("id")) for e in events]
    existing = {
        row[0]
        for row in db.query(GitHubEvent.gh_id).filter(GitHubEvent.gh_id.in_(ids)).all()
    }

    new_count = 0
    # Oldest first so stored/notified order matches real chronology.
    for ev in reversed(events):
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

    db.commit()
    if new_count:
        logger.info(
            "github poll stored events",
            extra={"extra_fields": {"repo": repo.full_name, "new_events": new_count}},
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
