"""Authentication: single-user login with password + optional TOTP 2FA.

Security notes:
  * Passwords and TOTP codes are NEVER placed in audit detail or logs.
  * Login failures return a generic message (no user enumeration).
  * Login is rate limited per (ip, username).
  * State-changing endpoints require a CSRF token.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..models.user import User
from ..providers import get_provider
from ..security.deps import (
    get_current_user,
    get_db,
    get_rate_limiter,
    get_session_data,
    get_session_store,
    require_csrf,
)
from ..security.passwords import verify_password
from ..security.sessions import SessionData, SessionStore
from ..security.totp import generate_secret, provisioning_uri, verify_totp
from .schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RevokeSessionRequest,
    SessionInfo,
    SimpleMessage,
    TotpDisableRequest,
    TotpEnableRequest,
    TotpSetupRequest,
    TotpSetupResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sid,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    limiter=Depends(get_rate_limiter),
) -> LoginResponse:
    ip = _client_ip(request)

    allowed, _ = limiter.hit(
        f"login:{ip}:{body.username}", settings.login_rate_limit_per_minute, 60
    )
    if not allowed:
        record_audit(
            db,
            action="auth.login.rate_limited",
            category="auth",
            success=False,
            ip=ip,
            detail={"username": body.username},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly.",
        )

    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(user.password_hash, body.password):
        record_audit(
            db,
            action="auth.login.failure",
            category="auth",
            success=False,
            ip=ip,
            detail={"username": body.username, "reason": "bad_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    if user.totp_enabled:
        if not body.totp_code or not verify_totp(user.totp_secret or "", body.totp_code):
            record_audit(
                db,
                action="auth.login.failure",
                category="auth",
                success=False,
                ip=ip,
                detail={"username": body.username, "reason": "totp_required_or_invalid"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Two-factor code required or invalid",
            )

    sess = store.create(
        user.id,
        meta={"ip": ip, "user_agent": request.headers.get("user-agent", "")[:200]},
    )
    _set_session_cookie(response, sess.sid)

    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    record_audit(
        db,
        action="auth.login.success",
        category="auth",
        success=True,
        ip=ip,
        detail={"username": body.username},
    )
    return LoginResponse(
        username=user.username, csrf_token=sess.csrf_token, totp_enabled=user.totp_enabled
    )


@router.post("/logout", response_model=SimpleMessage)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    data: SessionData = Depends(get_session_data),
    _: None = Depends(require_csrf),
) -> SimpleMessage:
    store.delete(data.sid)
    response.delete_cookie(settings.session_cookie_name, path="/")
    record_audit(db, action="auth.logout", category="auth", ip=_client_ip(request))
    return SimpleMessage(message="Logged out")


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),
    data: SessionData = Depends(get_session_data),
) -> MeResponse:
    return MeResponse(
        username=user.username,
        totp_enabled=user.totp_enabled,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        csrf_token=data.csrf_token,
        ai_available=get_provider().ai_available,
    )


@router.get("/sessions", response_model=list[SessionInfo])
def list_sessions(
    user: User = Depends(get_current_user),
    data: SessionData = Depends(get_session_data),
    store: SessionStore = Depends(get_session_store),
) -> list[SessionInfo]:
    return [
        SessionInfo(
            sid_masked=s.sid[:8] + "…",
            created_at=s.created_at,
            current=(s.sid == data.sid),
            meta=s.meta,
        )
        for s in store.list_for_user(user.id)
    ]


@router.post("/sessions/revoke", response_model=SimpleMessage)
def revoke_session(
    body: RevokeSessionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    store: SessionStore = Depends(get_session_store),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> SimpleMessage:
    target = store.get(body.sid)
    if target is not None and target.user_id == user.id:
        store.delete(body.sid)
        record_audit(
            db,
            action="auth.session.revoked",
            category="auth",
            ip=_client_ip(request),
            detail={"sid_masked": body.sid[:8] + "…"},
        )
    return SimpleMessage(message="Session revoked")


@router.post("/totp/setup", response_model=TotpSetupResponse)
def totp_setup(
    body: TotpSetupRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> TotpSetupResponse:
    # Re-authenticate with password before issuing a new TOTP secret.
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    secret = generate_secret()
    user.totp_secret = secret
    user.totp_enabled = False  # not active until a code is verified
    db.commit()
    record_audit(
        db, action="auth.totp.setup", category="auth", ip=_client_ip(request)
    )
    return TotpSetupResponse(
        secret=secret, provisioning_uri=provisioning_uri(secret, user.username)
    )


@router.post("/totp/enable", response_model=SimpleMessage)
def totp_enable(
    body: TotpEnableRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> SimpleMessage:
    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run TOTP setup first",
        )
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code"
        )
    user.totp_enabled = True
    db.commit()
    record_audit(db, action="auth.totp.enabled", category="auth", ip=_client_ip(request))
    return SimpleMessage(message="Two-factor authentication enabled")


@router.post("/totp/disable", response_model=SimpleMessage)
def totp_disable(
    body: TotpDisableRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> SimpleMessage:
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.totp_enabled or not verify_totp(user.totp_secret or "", body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code"
        )
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    record_audit(db, action="auth.totp.disabled", category="auth", ip=_client_ip(request))
    return SimpleMessage(message="Two-factor authentication disabled")
