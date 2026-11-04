"""Notification history — a record of every alert and how it was delivered."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "github"
    title: Mapped[str] = mapped_column(String(400))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)  # telegram | dashboard
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
