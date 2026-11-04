"""Fan out notifications to configured channels and record delivery history."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models.github import GitHubEvent
from ..models.notification import Notification
from .channels import DashboardChannel, NotificationChannel, TelegramChannel


class Notifier:
    def __init__(self, channels: list[NotificationChannel]) -> None:
        self.channels = channels

    def _dispatch(self, db: Session, category: str, title: str, body: str) -> None:
        for ch in self.channels:
            delivered, error = ch.send(title, body)
            db.add(
                Notification(
                    category=category,
                    title=title,
                    body=body,
                    channel=ch.name,
                    delivered=delivered,
                    error=error,
                )
            )

    def notify_github_event(self, db: Session, event: GitHubEvent) -> None:
        title = f"GitHub · {event.actor_login} {event.title}"
        lines = [
            f"Repo: {event.repo_full_name}",
            f"Actor: {event.actor_login} ({event.actor_type})",
            f"When: {event.created_at.isoformat()}",
        ]
        if event.summary:
            lines.append(event.summary)
        if event.url:
            lines.append(event.url)
        self._dispatch(db, "github", title, "\n".join(lines))


def build_notifier(http=None) -> Notifier:
    """Build a notifier from settings: dashboard always on; Telegram if
    a bot token and chat id are configured."""
    channels: list[NotificationChannel] = [DashboardChannel()]
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append(
            TelegramChannel(
                settings.telegram_bot_token, settings.telegram_chat_id, http=http
            )
        )
    return Notifier(channels)
