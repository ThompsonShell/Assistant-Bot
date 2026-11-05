from .conftest import login


def _auth(client):
    return {"X-CSRF-Token": login(client).json()["csrf_token"]}


def test_channels_requires_auth(client):
    assert client.get("/notifications/channels").status_code == 401


def test_channels_reports_telegram_not_configured(client):
    _auth(client)
    data = client.get("/notifications/channels").json()
    assert data["dashboard"] is True
    assert data["telegram_configured"] is False  # no token in tests


def test_send_test_delivers_to_dashboard(client):
    headers = _auth(client)
    r = client.post("/notifications/test", headers=headers)
    assert r.status_code == 200
    body = r.json()
    channels = {x["channel"]: x for x in body["results"]}
    assert channels["dashboard"]["delivered"] is True
    assert body["telegram_configured"] is False


def test_send_test_requires_csrf(client):
    login(client)
    assert client.post("/notifications/test").status_code == 403
