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
# Isolate tests from any real GITHUB_TOKEN present in the host environment,
# and never start the background scheduler during tests.
os.environ["GITHUB_TOKEN"] = ""
os.environ["ENABLE_SCHEDULER"] = "false"
# Isolate tests from any ambient Claude credentials; force the deterministic provider.
os.environ["ANTHROPIC_API_KEY"] = ""
import tempfile  # noqa: E402
os.environ.setdefault(
    "RUNTIME_STATE_FILE", os.path.join(tempfile.gettempdir(), "lifeos_test_runtime.json")
)
os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = ""
os.environ["USE_CLAUDE_SUBSCRIPTION"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

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
    return create_app(
        engine=engine,
        redis_client=redis_client,
        run_bootstrap=True,
        start_scheduler=False,
        start_telegram=False,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client: TestClient, totp_code: str | None = None):
    body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    if totp_code is not None:
        body["totp_code"] = totp_code
    return client.post("/auth/login", json=body)


# ── GitHub test helpers ──────────────────────────────────────────────

PUSH_EVENT = {
    "id": "1001",
    "type": "PushEvent",
    "actor": {"login": "alice"},
    "repo": {"name": "octo/demo"},
    "created_at": "2026-01-05T10:00:00Z",
    "payload": {
        "ref": "refs/heads/main",
        "size": 2,
        "commits": [{"message": "fix bug"}, {"message": "add feature"}],
    },
}

PR_BOT_EVENT = {
    "id": "1002",
    "type": "PullRequestEvent",
    "actor": {"login": "dependabot[bot]"},
    "repo": {"name": "octo/demo"},
    "created_at": "2026-01-05T11:00:00Z",
    "payload": {
        "action": "opened",
        "number": 7,
        "pull_request": {
            "number": 7,
            "title": "Bump lib",
            "html_url": "https://github.com/octo/demo/pull/7",
            "base": {"ref": "main"},
        },
    },
}

ACTION_EVENT = {
    "id": "1003",
    "type": "IssuesEvent",
    "actor": {"login": "github-actions[bot]"},
    "repo": {"name": "octo/demo"},
    "created_at": "2026-01-05T12:00:00Z",
    "payload": {
        "action": "closed",
        "issue": {"number": 3, "title": "flaky test", "html_url": "https://github.com/octo/demo/issues/3"},
    },
}

SAMPLE_EVENTS = [PUSH_EVENT, PR_BOT_EVENT, ACTION_EVENT]


class FakeGitHubClient:
    """Mimics GitHubClient.repo_events with no network. Returns a 304 when the
    caller presents the current ETag."""

    def __init__(self, events, etag="ETAG-1", commits=None, accessible=None):
        self.events = events
        self.etag = etag
        self.calls = 0
        self.commits = commits or []
        self.accessible = accessible or []

    def list_accessible_repos(self, per_page=100, max_pages=20):
        return self.accessible

    def repo_events(self, full_name, etag=None):
        self.calls += 1
        if etag == self.etag:
            return None, self.etag
        return self.events, self.etag

    def repo_commits(self, full_name, per_page=30):
        return self.commits
