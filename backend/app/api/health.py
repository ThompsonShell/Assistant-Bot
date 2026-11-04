"""Health and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from .. import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness: the process is up."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
def ready(request: Request) -> dict:
    """Readiness: dependencies (DB, Redis) are reachable."""
    checks: dict[str, str] = {}

    try:
        session_local = request.app.state.session_local
        with session_local() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - report, don't leak details
        checks["database"] = "error"

    try:
        request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"

    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
