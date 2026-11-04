"""GitHub monitoring models: watched repositories and ingested events."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class GitHubRepo(Base):
    """A repository we poll for activity."""

    __tablename__ = "github_repos"
    __table_args__ = (UniqueConstraint("full_name", name="uq_github_repos_full_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(320), index=True)  # owner/name
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # ETag for conditional requests (saves rate limit on unchanged polls).
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_polled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GitHubEvent(Base):
    """A single GitHub activity event, de-duplicated by its GitHub event id."""

    __tablename__ = "github_events"
    __table_args__ = (UniqueConstraint("gh_id", name="uq_github_events_gh_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gh_id: Mapped[str] = mapped_column(String(64), index=True)
    repo_full_name: Mapped[str] = mapped_column(String(320), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)  # PushEvent, ...
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_login: Mapped[str] = mapped_column(String(120), index=True)
    # human | bot | github_action | app | unknown  (never claims AI authorship)
    actor_type: Mapped[str] = mapped_column(String(32), index=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # PR/issue #
    title: Mapped[str] = mapped_column(String(400))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )  # when the event happened (UTC)
    ingested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # redacted payload
