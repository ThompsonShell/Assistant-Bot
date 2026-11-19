"""Self-study data: vocabulary cards (spaced repetition), daily diary, quizzes."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class VocabCard(Base):
    """One word to memorise, scheduled with the SM-2 spaced-repetition rules."""

    __tablename__ = "vocab_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(200), index=True)
    meaning: Mapped[str] = mapped_column(String(500))
    example: Mapped[str | None] = mapped_column(String(500), nullable=True)
    due_date: Mapped[dt.date] = mapped_column(Date, index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    reps: Mapped[int] = mapped_column(Integer, default=0)      # successful reviews in a row
    lapses: Mapped[int] = mapped_column(Integer, default=0)    # times forgotten
    last_reviewed: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiaryEntry(Base):
    """One entry per day: what I learned (input) and what I can recall (output)."""

    __tablename__ = "diary_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, unique=True, index=True)
    learned: Mapped[str] = mapped_column(Text, default="")    # input
    recalled: Mapped[str] = mapped_column(Text, default="")   # output, from memory
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QuizSession(Base):
    """A running or finished quiz. While unfinished, plain text replies from the
    owner are treated as answers."""

    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # [{"kind": "vocab"|"recall", "q": str, "a": str, "card_id": int|None}]
    questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    index: Mapped[int] = mapped_column(Integer, default=0)       # next question to ask
    correct: Mapped[float] = mapped_column(Float, default=0.0)   # partial credit allowed
    finished: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class ReadingLog(Base):
    """One reading session (vocab text, technical article or space article)."""

    __tablename__ = "reading_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))              # vocab | tech | space
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    blurb: Mapped[str | None] = mapped_column(String(400), nullable=True)
    words_sent: Mapped[int] = mapped_column(Integer, default=0)  # unknown words saved (max 5)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 2 English sentences
    example_done: Mapped[bool] = mapped_column(Boolean, default=False)  # tried a docs example
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | done
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudyKV(Base):
    """Small key/value store for study settings (current weekly topic, start date)."""

    __tablename__ = "study_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class PaperEntry(Base):
    """A handwritten diary page sent as a photo (one row per day).

    Nothing counts in statistics until ``confirmed`` is true: the owner checks
    what the bot read from the page and presses Confirm.
    """

    __tablename__ = "paper_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, unique=True, index=True)
    photo_paths: Mapped[list[Any]] = mapped_column(JSON, default=list)
    transcription: Mapped[str] = mapped_column(Text, default="")        # as read, never "fixed"
    parsed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # learned, output, mistakes, ...
    minutes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict) # python, sql, english, algo, other
    ai_off_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)      # asked once next morning
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
