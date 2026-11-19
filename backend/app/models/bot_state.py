"""Conversation state for guided flows (one row per chat)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ConversationState(Base):
    """What the bot is waiting for from the owner, e.g. the text for /word.

    ``state`` is a short key such as ``flow:/word``; ``data`` holds the details
    the next message needs (an entry id, a field name, ...).
    """

    __tablename__ = "conversation_state"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)  # chat key ("owner")
    state: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
