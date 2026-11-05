"""GitHub analytics computed from stored events (real data only).

Note on interpretation: counts describe *activity volume*, not productivity.
Commit/event counts are context-dependent and must not be read as a measure of
quality or effort.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from sqlalchemy.orm import Session

from ..models.github import GitHubEvent


def github_summary(
    db: Session, start: dt.datetime, end: dt.datetime
) -> dict:
    events = (
        db.query(GitHubEvent)
        .filter(GitHubEvent.created_at >= start, GitHubEvent.created_at < end)
        .all()
    )

    by_type: Counter[str] = Counter(e.type for e in events)
    by_actor_type: Counter[str] = Counter(e.actor_type for e in events)
    by_repo: Counter[str] = Counter(e.repo_full_name for e in events)
    by_actor: Counter[str] = Counter(e.actor_login for e in events)
    by_day: Counter[str] = Counter(e.created_at.date().isoformat() for e in events)
    by_hour: Counter[int] = Counter(e.created_at.hour for e in events)

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "total_events": len(events),
        "commits": by_type.get("Commit", 0),
        "pushes": by_type.get("PushEvent", 0),
        "pull_requests": by_type.get("PullRequestEvent", 0),
        "pull_request_reviews": by_type.get("PullRequestReviewEvent", 0),
        "issues": by_type.get("IssuesEvent", 0),
        "issue_comments": by_type.get("IssueCommentEvent", 0),
        "by_type": dict(by_type),
        "by_actor_type": dict(by_actor_type),
        "by_repo": dict(by_repo.most_common()),
        "by_actor": dict(by_actor.most_common(20)),
        "by_day": dict(sorted(by_day.items())),
        "by_hour": {str(h): by_hour.get(h, 0) for h in range(24)},
        "human_events": by_actor_type.get("human", 0),
        "automation_events": (
            by_actor_type.get("bot", 0)
            + by_actor_type.get("github_action", 0)
            + by_actor_type.get("app", 0)
        ),
        "note": "Counts reflect activity volume, not productivity or quality.",
    }
