"""Minimal read-only GitHub REST client (polling the Events API).

The client is constructed around an injected ``httpx.Client`` so tests can
supply a mock transport with no network access.
"""
from __future__ import annotations

from typing import Any

import httpx

from ...config import settings

USER_AGENT = "AI-LifeOS/0.1 (+personal monitor)"


class GitHubClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def repo_events(
        self, full_name: str, etag: str | None = None
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Fetch recent events for ``owner/name``.

        Returns ``(events, new_etag)``. If GitHub replies 304 Not Modified,
        returns ``(None, etag)`` so the caller can skip processing.
        """
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        resp = self._http.get(
            f"/repos/{full_name}/events",
            params={"per_page": 100},
            headers=headers,
        )
        if resp.status_code == 304:
            return None, etag
        resp.raise_for_status()
        return resp.json(), resp.headers.get("ETag")

    def repo_commits(
        self, full_name: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """Fetch recent commits for ``owner/name`` (works for private repos and
        has no events-feed delay)."""
        resp = self._http.get(
            f"/repos/{full_name}/commits", params={"per_page": per_page}
        )
        if resp.status_code in (404, 409):
            # 409 = empty repository; 404 = not found / no access.
            return []
        resp.raise_for_status()
        return resp.json()


def make_github_client(token: str | None = None) -> GitHubClient:
    token = token or settings.github_token
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http = httpx.Client(base_url=settings.github_api_base, headers=headers, timeout=20.0)
    return GitHubClient(http)
