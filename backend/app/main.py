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
from .api import health as health_api
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


def create_app(
    *,
    engine: Engine | None = None,
    redis_client=None,
    run_bootstrap: bool = True,
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

    return app
