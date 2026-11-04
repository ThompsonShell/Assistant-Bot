"""Server-side sessions stored in Redis.

A random session id lives in a secure cookie; all session state (user id, CSRF
token, metadata) is kept server-side so sessions are revocable and listable.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass
from typing import Any


def _utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass
class SessionData:
    sid: str
    user_id: int
    csrf_token: str
    created_at: str
    meta: dict[str, Any]


class SessionStore:
    def __init__(self, redis_client: Any, ttl_seconds: int) -> None:
        self._r = redis_client
        self._ttl = ttl_seconds

    @staticmethod
    def _skey(sid: str) -> str:
        return f"session:{sid}"

    @staticmethod
    def _ukey(user_id: int) -> str:
        return f"user_sessions:{user_id}"

    def create(self, user_id: int, meta: dict[str, Any] | None = None) -> SessionData:
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        data = SessionData(
            sid=sid,
            user_id=user_id,
            csrf_token=csrf,
            created_at=_utcnow_iso(),
            meta=meta or {},
        )
        self._r.setex(
            self._skey(sid),
            self._ttl,
            json.dumps(
                {
                    "user_id": user_id,
                    "csrf_token": csrf,
                    "created_at": data.created_at,
                    "meta": data.meta,
                }
            ),
        )
        self._r.sadd(self._ukey(user_id), sid)
        return data

    def get(self, sid: str) -> SessionData | None:
        if not sid:
            return None
        raw = self._r.get(self._skey(sid))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(raw)
        return SessionData(
            sid=sid,
            user_id=payload["user_id"],
            csrf_token=payload["csrf_token"],
            created_at=payload["created_at"],
            meta=payload.get("meta", {}),
        )

    def touch(self, sid: str) -> None:
        """Extend the TTL on access (sliding expiration)."""
        self._r.expire(self._skey(sid), self._ttl)

    def delete(self, sid: str) -> None:
        data = self.get(sid)
        self._r.delete(self._skey(sid))
        if data is not None:
            self._r.srem(self._ukey(data.user_id), sid)

    def list_for_user(self, user_id: int) -> list[SessionData]:
        members = self._r.smembers(self._ukey(user_id))
        out: list[SessionData] = []
        for m in members:
            sid = m.decode() if isinstance(m, bytes) else m
            data = self.get(sid)
            if data is None:
                # Expired: clean up the index.
                self._r.srem(self._ukey(user_id), sid)
            else:
                out.append(data)
        return sorted(out, key=lambda d: d.created_at, reverse=True)
