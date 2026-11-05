"""Notification settings + a test-send endpoint to verify delivery."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..models.user import User
from ..notifications import build_notifier
from ..security.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/channels")
def channels(_: User = Depends(get_current_user)) -> dict:
    """Which notification channels are active."""
    return {
        "dashboard": True,
        "telegram_configured": bool(
            settings.telegram_bot_token and settings.telegram_chat_id
        ),
    }


@router.post("/test")
def send_test(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> dict:
    """Send a test notification through every configured channel.

    If Telegram is configured, you should receive a message in your chat. The
    'dashboard' channel always succeeds (it just records the notification)."""
    notifier = build_notifier()
    results = notifier.notify(
        db,
        "test",
        "✅ LifeOS test",
        "If you can read this in Telegram, your notifications are working!",
    )
    record_audit(
        db,
        action="notifications.test",
        category="notifications",
        detail={"channels": [r["channel"] for r in results]},
    )
    return {
        "results": results,
        "telegram_configured": bool(
            settings.telegram_bot_token and settings.telegram_chat_id
        ),
    }
