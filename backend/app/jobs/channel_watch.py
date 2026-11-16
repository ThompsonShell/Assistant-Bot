"""Periodic job: forward relevant posts from watched public Telegram channels.

Only ever sends to the owner's chat. Does nothing when Telegram or
WATCH_CHANNELS is not configured. Errors are logged, never raised, so the
scheduler keeps running.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.jobs.channels")


def run_channel_watch(*, http: httpx.Client | None = None) -> int:
    """Check watched channels and forward new relevant posts. Returns the
    number of posts sent."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return 0

    from ..integrations.channels import collect_relevant, format_post, watched_channels
    from .telegram_bot import send_message

    if not watched_channels():
        return 0

    own = http is None
    client = http or httpx.Client(timeout=30)
    sent = 0
    try:
        for post, hits in collect_relevant(http=client):
            send_message(client, settings.telegram_chat_id, format_post(post, hits))
            sent += 1
    except Exception as exc:  # noqa: BLE001 - never crash the scheduler
        logger.warning("channel watch failed", extra={"extra_fields": {"error": str(exc)[:200]}})
    finally:
        if own:
            client.close()
    if sent:
        logger.info("channel watch forwarded posts", extra={"extra_fields": {"count": sent}})
    return sent
