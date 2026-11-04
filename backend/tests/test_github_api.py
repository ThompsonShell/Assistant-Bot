from .conftest import SAMPLE_EVENTS, FakeGitHubClient, login


def _auth(client):
    return {"X-CSRF-Token": login(client).json()["csrf_token"]}


def test_github_api_requires_auth(client):
    assert client.get("/github/repos").status_code == 401
    assert client.get("/github/events").status_code == 401


def test_add_list_and_remove_repo(client):
    headers = _auth(client)
    r = client.post("/github/repos", json={"owner": "octo", "name": "demo"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["full_name"] == "octo/demo"
    repo_id = r.json()["id"]

    # Duplicate -> 409.
    assert client.post(
        "/github/repos", json={"owner": "octo", "name": "demo"}, headers=headers
    ).status_code == 409

    assert len(client.get("/github/repos").json()) == 1

    assert client.delete(f"/github/repos/{repo_id}", headers=headers).status_code == 200
    assert len(client.get("/github/repos").json()) == 0


def test_add_repo_requires_csrf(client):
    login(client)  # authenticated but no CSRF header
    assert client.post("/github/repos", json={"owner": "o", "name": "r"}).status_code == 403


def test_poll_events_and_analytics(app, client):
    headers = _auth(client)
    client.post("/github/repos", json={"owner": "octo", "name": "demo"}, headers=headers)

    # Inject a fake GitHub client (no network).
    app.state.github_client = FakeGitHubClient(SAMPLE_EVENTS)

    poll = client.post("/github/poll", headers=headers)
    assert poll.status_code == 200
    assert poll.json()["polled"]["octo/demo"] == 3

    events = client.get("/github/events").json()
    assert len(events) == 3
    # Most recent first.
    assert events[0]["created_at"] >= events[-1]["created_at"]

    # Filter by actor type.
    bots = client.get("/github/events", params={"actor_type": "bot"}).json()
    assert len(bots) == 1 and bots[0]["actor_login"] == "dependabot[bot]"

    analytics = client.get("/github/analytics", params={"range": "year"}).json()
    assert analytics["total_events"] == 3
    assert analytics["pushes"] == 1
    assert analytics["pull_requests"] == 1
    assert analytics["human_events"] == 1
    assert analytics["automation_events"] == 2

    notes = client.get("/github/notifications").json()
    assert len(notes) == 3


def test_poll_without_token_errors(app, client):
    headers = _auth(client)
    client.post("/github/repos", json={"owner": "octo", "name": "demo"}, headers=headers)
    # No github_client injected and no GITHUB_TOKEN configured.
    assert getattr(app.state, "github_client", None) is None
    assert client.post("/github/poll", headers=headers).status_code == 400


def test_analytics_bad_range(client):
    _auth(client)
    assert client.get("/github/analytics", params={"range": "decade"}).status_code == 400
