"""Chat history with the AI assistant."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), index=True)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
