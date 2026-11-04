"""Test fixtures: an app wired to in-memory SQLite + fakeredis.

No Postgres or Redis server is required to run the suite.
"""
from __future__ import annotations

import os

# Configure settings BEFORE importing the app (config reads env at import).
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "Test-Passw0rd!")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("LOGIN_RATE_LIMIT_PER_MINUTE", "5")

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import make_engine  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Test-Passw0rd!"


@pytest.fixture
def app():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    redis_client = fakeredis.FakeStrictRedis()
    return create_app(engine=engine, redis_client=redis_client, run_bootstrap=True)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client: TestClient, totp_code: str | None = None):
    body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    if totp_code is not None:
        body["totp_code"] = totp_code
    return client.post("/auth/login", json=body)
