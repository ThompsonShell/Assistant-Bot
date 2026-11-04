"""Notification channels.

SECURITY: these only ever notify YOU (the admin). The Telegram channel sends
to your own configured chat id and nothing else. There is no code path that
messages any contact — that is a hard project rule.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger("lifeos.notifications")


class NotificationChannel(Protocol):
    name: str

    def send(self, title: str, body: str) -> tuple[bool, str | None]:
        """Return (delivered, error_message)."""
        ...


class DashboardChannel:
    """A no-op delivery channel: the event is recorded and shown in the
    dashboard feed. Always 'delivered' since it is just persistence."""

    name = "dashboard"

    def send(self, title: str, body: str) -> tuple[bool, str | None]:
        return True, None


class TelegramChannel:
    """Sends a message to your own Telegram chat via the Bot API (outbound
    only; no public URL needed)."""

    name = "telegram"

    def __init__(self, token: str, chat_id: str, http: httpx.Client | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._http = http or httpx.Client(timeout=15.0)

    def send(self, title: str, body: str) -> tuple[bool, str | None]:
        text = f"{title}\n\n{body}" if body else title
        try:
            resp = self._http.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text[:4000]},
            )
            resp.raise_for_status()
            return True, None
        except Exception as exc:  # noqa: BLE001
            # Never log the token; only a short error string.
            msg = str(exc)[:200]
            logger.warning("telegram send failed", extra={"extra_fields": {"error": msg}})
            return False, msg
