"""GitHub monitoring API: manage watched repos, view events, analytics, poll."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..integrations.github import make_github_client, poll_all
from ..integrations.github.client import GitHubClient
from ..models.github import GitHubEvent, GitHubRepo
from ..models.notification import Notification
from ..models.user import User
from ..notifications import build_notifier
from ..security.deps import get_current_user, get_db, require_csrf
from ..analytics import compute_range, github_summary
from ..analytics.ranges import VALID_RANGES
from .github_schemas import (
    EventInfo,
    NotificationInfo,
    PollResult,
    RepoCreate,
    RepoInfo,
    WatchAllRequest,
    WatchAllResult,
)
from .schemas import SimpleMessage

router = APIRouter(prefix="/github", tags=["github"])


def _client(request: Request) -> GitHubClient:
    """Use an injected client (tests) or build one from settings."""
    injected = getattr(request.app.state, "github_client", None)
    if injected is not None:
        return injected
    if not settings.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GITHUB_TOKEN is not configured",
        )
    return make_github_client()


@router.get("/repos", response_model=list[RepoInfo])
def list_repos(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[GitHubRepo]:
    return db.query(GitHubRepo).order_by(GitHubRepo.full_name).all()


@router.post("/repos", response_model=RepoInfo, status_code=status.HTTP_201_CREATED)
def add_repo(
    body: RepoCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> GitHubRepo:
    full_name = f"{body.owner}/{body.name}"
    if db.query(GitHubRepo).filter(GitHubRepo.full_name == full_name).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Repo already watched"
        )
    repo = GitHubRepo(owner=body.owner, name=body.name, full_name=full_name, active=True)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    record_audit(
        db,
        action="github.repo.added",
        category="github",
        detail={"full_name": full_name},
    )
    return repo


@router.post("/repos/watch-all", response_model=WatchAllResult)
def watch_all(
    body: WatchAllRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> WatchAllResult:
    """Watch every repository the token can access (optionally one owner)."""
    client = _client(request)
    owner_filter = (body.owner or "").strip().lower()
    try:
        repos = client.list_accessible_repos()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Could not list your repositories. GITHUB_TOKEN must be a "
                "fine-grained Personal Access Token (or classic PAT) with read "
                "access to your repos. Add repos one by one with /github/repos "
                "if needed. (" + str(exc)[:120] + ")"
            ),
        )

    existing = {row[0] for row in db.query(GitHubRepo.full_name).all()}
    added: list[str] = []
    skipped = 0
    for r in repos:
        owner = (r.get("owner") or {}).get("login") or ""
        name = r.get("name") or ""
        if not owner or not name:
            continue
        if owner_filter and owner.lower() != owner_filter:
            continue
        full = f"{owner}/{name}"
        if full in existing:
            skipped += 1
            continue
        db.add(GitHubRepo(owner=owner, name=name, full_name=full, active=True))
        existing.add(full)
        added.append(full)
    db.commit()
    record_audit(
        db,
        action="github.repos.watch_all",
        category="github",
        detail={"added": len(added), "owner": owner_filter or "all"},
    )
    return WatchAllResult(added=sorted(added), already_watched=skipped)


@router.delete("/repos/{repo_id}", response_model=SimpleMessage)
def remove_repo(
    repo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> SimpleMessage:
    repo = db.get(GitHubRepo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    full_name = repo.full_name
    db.delete(repo)
    db.commit()
    record_audit(
        db, action="github.repo.removed", category="github", detail={"full_name": full_name}
    )
    return SimpleMessage(message=f"Stopped watching {full_name}")


@router.get("/events", response_model=list[EventInfo])
def list_events(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    repo: str | None = None,
    actor_type: str | None = None,
) -> list[GitHubEvent]:
    q = db.query(GitHubEvent)
    if repo:
        q = q.filter(GitHubEvent.repo_full_name == repo)
    if actor_type:
        q = q.filter(GitHubEvent.actor_type == actor_type)
    return q.order_by(GitHubEvent.created_at.desc()).limit(limit).all()


@router.get("/analytics")
def analytics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    range: str = Query("week"),
) -> dict:
    if range not in VALID_RANGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"range must be one of {', '.join(VALID_RANGES)}",
        )
    start, end = compute_range(range, settings.display_timezone)
    data = github_summary(db, start, end)
    data["range_name"] = range
    data["timezone"] = settings.display_timezone
    return data


@router.get("/notifications", response_model=list[NotificationInfo])
def notification_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[Notification]:
    return db.query(Notification).order_by(Notification.ts.desc()).limit(limit).all()


@router.post("/poll", response_model=PollResult)
def poll_now(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> PollResult:
    client = _client(request)
    notifier = build_notifier()
    results = poll_all(db, client, notifier)
    db.commit()
    record_audit(db, action="github.poll.manual", category="github", detail=results)
    return PollResult(polled=results)
