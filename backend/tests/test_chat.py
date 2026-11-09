from .conftest import login


def _auth(client):
    return {"X-CSRF-Token": login(client).json()["csrf_token"]}


def test_chat_requires_auth(client):
    assert client.get("/chat/history").status_code == 401
    assert client.post("/chat", json={"message": "hi"}).status_code in (401, 403)


def test_chat_stores_and_replies(client):
    headers = _auth(client)
    r = client.post("/chat", json={"message": "salom"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ai_available"] is False  # deterministic provider in tests
    assert isinstance(body["reply"], str) and body["reply"]

    hist = client.get("/chat/history").json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[0]["content"] == "salom"


def test_chat_requires_csrf(client):
    login(client)
    assert client.post("/chat", json={"message": "x"}).status_code == 403


def test_clear_history(client):
    headers = _auth(client)
    client.post("/chat", json={"message": "a"}, headers=headers)
    assert len(client.get("/chat/history").json()) == 2
    r = client.request("DELETE", "/chat/history", headers=headers)
    assert r.status_code == 200
    assert client.get("/chat/history").json() == []
