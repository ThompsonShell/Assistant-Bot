"""Application factory.

Run with:  uvicorn app.main:create_app --factory
Tests build their own app via create_app(engine=..., redis_client=...).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from . import __version__
from .api import auth as auth_api
from .api import calendar as calendar_api
from .api import chat as chat_api
from .api import github as github_api
from .api import health as health_api
from .api import notifications as notifications_api
from .api import web as web_api
from .config import settings
from .db import Base, make_engine, make_sessionmaker
from .logging_config import configure_logging
from .models.user import User
from .redis_client import get_redis
from .security.passwords import hash_password
from .security.ratelimit import RateLimiter
from .security.sessions import SessionStore

logger = logging.getLogger("lifeos.startup")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def bootstrap_admin(session_local: sessionmaker) -> None:
    """Create the single admin user on first run from env, if none exists.

    Never overwrites an existing user. The password is hashed; nothing secret
    is logged.
    """
    with session_local() as db:
        existing = db.query(User).count()
        if existing > 0:
            return
        if not settings.admin_password:
            logger.warning(
                "No user exists and ADMIN_PASSWORD is unset — login is not "
                "possible until you set it and restart."
            )
            return
        user = User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            totp_enabled=False,
        )
        db.add(user)
        db.commit()
        logger.info(
            "Bootstrapped admin user",
            extra={"extra_fields": {"username": settings.admin_username}},
        )


def _start_scheduler(app: FastAPI, session_local: sessionmaker) -> None:
    """Start background jobs (best-effort; APScheduler is an optional dependency).

    Runs independent jobs when their prerequisites are met:
      - GitHub poll loop (needs GITHUB_TOKEN)
      - daily morning briefing at the configured hour (needs Telegram configured)
      - public Telegram channel watch (needs Telegram + WATCH_CHANNELS)
      - study reminders: due words, diary, quiz (needs Telegram)
    """
    if not settings.enable_scheduler:
        return
    github_on = bool(settings.github_token)
    telegram_on = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    morning_on = telegram_on and settings.morning_brief_enabled
    channels_on = telegram_on and bool(settings.watch_channels.strip())
    study_on = telegram_on and settings.study_enabled
    if not (github_on or morning_on or channels_on or study_on):
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler not started: %s", str(exc)[:200])
        return

    scheduler = BackgroundScheduler(daemon=True)

    if github_on:
        from .jobs.github_poll import run_poll_once

        scheduler.add_job(
            lambda: run_poll_once(session_local),
            "interval",
            seconds=max(30, settings.github_poll_interval_seconds),
            id="github_poll",
            max_instances=1,
            coalesce=True,
        )

    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(settings.display_timezone)
    except Exception:  # noqa: BLE001 - fall back to UTC on a bad tz name
        tz = ZoneInfo("UTC")

    if morning_on:
        from .jobs.morning import send_morning_weather

        scheduler.add_job(
            send_morning_weather,
            CronTrigger(
                hour=settings.morning_brief_hour,
                minute=settings.morning_brief_minute,
                timezone=tz,
            ),
            id="morning_brief",
            max_instances=1,
            coalesce=True,
        )

    if study_on:
        from .jobs import study_reminders as sr

        hours = ",".join(
            h.strip() for h in settings.study_review_hours.split(",") if h.strip().isdigit()
        )
        study_jobs = [
            ("study_diary", sr.remind_diary, str(settings.study_diary_hour)),
            ("study_quiz", sr.remind_quiz, str(settings.study_quiz_hour)),
        ]
        if hours:
            study_jobs.append(("study_review", sr.remind_review, hours))
        for job_id, func, hour in study_jobs:
            scheduler.add_job(
                lambda f=func: f(session_local),
                CronTrigger(hour=hour, minute=0, timezone=tz),
                id=job_id,
                max_instances=1,
                coalesce=True,
            )

    if channels_on:
        from .jobs.channel_watch import run_channel_watch

        scheduler.add_job(
            run_channel_watch,
            "interval",
            minutes=max(5, settings.channel_poll_minutes),
            id="channel_watch",
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "scheduler started",
        extra={"extra_fields": {
            "github_poll": github_on,
            "morning_brief": morning_on,
            "channel_watch": channels_on,
            "study_reminders": study_on,
            "morning_at": f"{settings.morning_brief_hour:02d}:{settings.morning_brief_minute:02d}",
        }},
    )


def _start_telegram_bot(app: FastAPI) -> None:
    """Start the two-way Telegram bot in a daemon thread (best-effort)."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return
    try:
        import threading

        from .jobs.telegram_bot import run_bot
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram bot not started: %s", str(exc)[:200])
        return
    thread = threading.Thread(target=run_bot, name="telegram-bot", daemon=True)
    thread.start()
    app.state.telegram_thread = thread
    logger.info("telegram bot thread started")


def create_app(
    *,
    engine: Engine | None = None,
    redis_client=None,
    run_bootstrap: bool = True,
    start_scheduler: bool = True,
    start_telegram: bool = True,
) -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Private AI LifeOS",
        version=__version__,
        description="Private, single-user personal intelligence platform.",
    )

    engine = engine or make_engine(settings.database_url)
    session_local = make_sessionmaker(engine)
    app.state.engine = engine
    app.state.session_local = session_local

    redis_client = redis_client or get_redis(settings.redis_url)
    app.state.redis = redis_client
    app.state.session_store = SessionStore(redis_client, settings.session_ttl_seconds)
    app.state.rate_limiter = RateLimiter(redis_client)

    if settings.auto_create_tables:
        Base.metadata.create_all(engine)

    if run_bootstrap:
        bootstrap_admin(session_local)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.include_router(health_api.router)
    app.include_router(auth_api.router)
    app.include_router(github_api.router)
    app.include_router(notifications_api.router)
    app.include_router(calendar_api.router)
    app.include_router(chat_api.router)
    app.include_router(web_api.router)

    if start_scheduler:
        _start_scheduler(app, session_local)

    if start_telegram:
        _start_telegram_bot(app)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    return app
