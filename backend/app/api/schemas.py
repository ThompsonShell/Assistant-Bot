"""Request/response models for the API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = Field(default=None, max_length=12)


class LoginResponse(BaseModel):
    username: str
    csrf_token: str
    totp_enabled: bool


class MeResponse(BaseModel):
    username: str
    totp_enabled: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None
    csrf_token: str
    ai_available: bool


class SessionInfo(BaseModel):
    sid_masked: str
    created_at: str
    current: bool
    meta: dict


class RevokeSessionRequest(BaseModel):
    sid: str = Field(min_length=1, max_length=128)


class TotpSetupRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class TotpDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=6, max_length=12)


class SimpleMessage(BaseModel):
    message: str
