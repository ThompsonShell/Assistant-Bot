"""FastAPI dependencies for DB sessions, auth, and CSRF.

Shared infrastructure (sessionmaker, session store, rate limiter) lives on
``request.app.state`` so it can be wired per-app and overridden in tests.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..models.user import User
from .sessions import SessionData, SessionStore


def get_db(request: Request) -> Iterator[Session]:
    session_local = request.app.state.session_local
    db = session_local()
    try:
        yield db
    finally:
        db.close()


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_rate_limiter(request: Request):
    return request.app.state.rate_limiter


def get_session_data(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> SessionData:
    sid = request.cookies.get(settings.session_cookie_name, "")
    data = store.get(sid)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    store.touch(sid)
    return data


def get_current_user(
    data: SessionData = Depends(get_session_data),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, data.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def require_csrf(
    request: Request,
    data: SessionData = Depends(get_session_data),
) -> None:
    """Enforce CSRF on state-changing requests via a per-session token header."""
    sent = request.headers.get("X-CSRF-Token", "")
    if not sent or sent != data.csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalid or missing"
        )
