"""Schemas for the GitHub monitoring API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator


class RepoCreate(BaseModel):
    owner: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("owner", "name")
    @classmethod
    def _no_slash(cls, v: str) -> str:
        v = v.strip()
        if "/" in v or not v:
            raise ValueError("must not be empty or contain '/'")
        return v


class WatchAllRequest(BaseModel):
    # Optional: only watch repos whose owner matches (case-insensitive).
    # Empty = watch every repository the token can access.
    owner: str | None = Field(default=None, max_length=120)


class WatchAllResult(BaseModel):
    added: list[str]
    already_watched: int
    note: str = "Watches every accessible repo (or those of the given owner)."


class RepoInfo(BaseModel):
    id: int
    full_name: str
    active: bool
    created_at: dt.datetime
    last_polled_at: dt.datetime | None


class EventInfo(BaseModel):
    id: int
    repo_full_name: str
    type: str
    actor_login: str
    actor_type: str
    title: str
    summary: str | None
    branch: str | None
    number: int | None
    url: str | None
    created_at: dt.datetime


class NotificationInfo(BaseModel):
    id: int
    ts: dt.datetime
    category: str
    title: str
    channel: str
    delivered: bool
    error: str | None


class PollResult(BaseModel):
    polled: dict[str, int]
    note: str = "Values are new events per repo; -1 means that repo errored."
