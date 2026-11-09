"""Calendar tasks (manual or AI-planned)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # high|medium|low
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)  # planned|done|missed
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|ai
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
