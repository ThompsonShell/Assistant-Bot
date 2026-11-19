"""Read/write the owner's conversation state (what the bot is waiting for)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..models.bot_state import ConversationState

KEY = "owner"            # single-user bot: one conversation
TTL = dt.timedelta(minutes=30)  # a forgotten question stops capturing messages


def _aware(ts: dt.datetime) -> dt.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def get_state(db, now: dt.datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    row = db.get(ConversationState, KEY)
    if row is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if now - _aware(row.updated_at) > TTL:
        db.delete(row)
        db.commit()
        return None
    return row.state, dict(row.data or {})


def set_state(db, state: str, data: dict[str, Any] | None = None) -> None:
    row = db.get(ConversationState, KEY)
    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        db.add(ConversationState(key=KEY, state=state, data=data or {}, updated_at=now))
    else:
        row.state, row.data, row.updated_at = state, data or {}, now
    db.commit()


def clear_state(db) -> bool:
    """Forget the pending question. Returns True if there was one."""
    row = db.get(ConversationState, KEY)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
