import pyotp

from .conftest import ADMIN_PASSWORD, ADMIN_USERNAME, login


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["checks"]["database"] == "ok"
    assert ready["checks"]["redis"] == "ok"


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_login_wrong_password(client):
    r = client.post(
        "/auth/login", json={"username": ADMIN_USERNAME, "password": "nope"}
    )
    assert r.status_code == 401


def test_login_success_and_me(client):
    r = login(client)
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == ADMIN_USERNAME
    assert data["totp_enabled"] is False
    csrf = data["csrf_token"]

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == ADMIN_USERNAME
    assert me.json()["csrf_token"] == csrf
    assert me.json()["ai_available"] is False


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_logout_requires_csrf_then_clears_session(client):
    csrf = login(client).json()["csrf_token"]

    # Missing CSRF header -> rejected.
    assert client.post("/auth/logout").status_code == 403

    # With CSRF header -> logged out.
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200

    # Session is gone.
    assert client.get("/auth/me").status_code == 401


def test_login_rate_limited(client):
    # Limit is 5/min; the 6th attempt should be throttled.
    codes = [
        client.post(
            "/auth/login", json={"username": ADMIN_USERNAME, "password": "bad"}
        ).status_code
        for _ in range(6)
    ]
    assert codes[-1] == 429
    assert 401 in codes[:5]


def test_sessions_list_shows_current(client):
    csrf = login(client).json()["csrf_token"]
    sessions = client.get("/auth/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["current"] is True
    assert sessions[0]["sid_masked"].endswith("…")
    # Masked id must not expose the full session id.
    assert len(sessions[0]["sid_masked"]) <= 12


def test_totp_setup_enable_and_enforced_at_login(client):
    csrf = login(client).json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    setup = client.post(
        "/auth/totp/setup", json={"password": ADMIN_PASSWORD}, headers=headers
    )
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["provisioning_uri"].startswith("otpauth://")

    enable = client.post(
        "/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers
    )
    assert enable.status_code == 200

    client.post("/auth/logout", headers=headers)

    # Now login without a code must fail.
    assert login(client).status_code == 401

    # With a valid code it succeeds.
    assert login(client, totp_code=pyotp.TOTP(secret).now()).status_code == 200
