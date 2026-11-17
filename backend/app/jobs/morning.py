"""Daily morning briefing: weather + clothing advice pushed to the owner.

Scheduled by the app factory to run once every morning (default 08:00 in the
display timezone). It only ever messages the configured owner chat — never a
contact — and silently no-ops when Telegram isn't configured.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.jobs.morning")


def _send_news(client: httpx.Client) -> None:
    """Send top tech and space stories as photo cards after the weather message.

    Never raises: a news outage must not turn the morning brief into an error.
    """
    if not settings.news_enabled:
        return
    from .telegram_bot import send_news_cards

    for topic, count, heading in (
        ("tech", settings.news_morning_count, "🌍 Bugungi yangiliklar"),
        ("space", settings.news_morning_space_count, "🚀 Kosmos"),
    ):
        if count <= 0:
            continue
        try:
            send_news_cards(
                client, settings.telegram_chat_id, limit=count, heading=heading, topic=topic
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "morning news failed",
                extra={"extra_fields": {"topic": topic, "error": str(exc)[:200]}},
            )


def send_morning_weather(*, http: httpx.Client | None = None) -> bool:
    """Send the morning weather + clothing tip to the owner's Telegram.

    Returns True when a message was sent, False when Telegram is not
    configured. Errors are logged, not raised, so a bad morning never stops
    the scheduler.
    """
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        logger.info("morning brief skipped: telegram not configured")
        return False

    from .telegram_bot import _weather_text, send_message

    own = http is None
    client = http or httpx.Client(timeout=30)
    try:
        text = "☀️ *Xayrli tong!*\n\n" + _weather_text()
        send_message(client, settings.telegram_chat_id, text)
        _send_news(client)
        logger.info("morning brief sent")
        return True
    except Exception as exc:  # noqa: BLE001 - never crash the scheduler
        logger.warning("morning brief failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return False
    finally:
        if own:
            client.close()
