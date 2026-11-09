import datetime as dt

from .conftest import login


def _auth(client):
    return {"X-CSRF-Token": login(client).json()["csrf_token"]}


def test_calendar_requires_auth(client):
    assert client.get("/calendar/tasks").status_code == 401


def test_plan_proposes_tasks(client):
    headers = _auth(client)
    r = client.post(
        "/calendar/plan",
        json={"text": "study backend, english practice, finish dashboard"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ai_generated"] is False  # deterministic in tests
    assert len(body["tasks"]) == 3
    titles = [t["title"] for t in body["tasks"]]
    assert "study backend" in titles


def test_save_list_update_delete(client):
    headers = _auth(client)
    monday = "2026-11-09"
    save = client.post(
        "/calendar/tasks",
        json={
            "week_start": monday,
            "tasks": [
                {"title": "Backend", "day": "Monday", "duration_minutes": 90, "priority": "high"},
                {"title": "English", "day": "Tuesday", "duration_minutes": 45},
            ],
        },
        headers=headers,
    )
    assert save.status_code == 201
    saved = save.json()
    assert len(saved) == 2
    # Monday maps onto the given week start.
    backend = next(t for t in saved if t["title"] == "Backend")
    assert backend["scheduled_date"] == monday

    # List.
    assert len(client.get("/calendar/tasks").json()) == 2

    # Mark done.
    tid = backend["id"]
    upd = client.patch(f"/calendar/tasks/{tid}", json={"status": "done"}, headers=headers)
    assert upd.status_code == 200 and upd.json()["status"] == "done"

    # Analytics reflect completion.
    an = client.get("/calendar/analytics", params={"days": 365}).json()
    assert an["total"] == 2 and an["done"] == 1

    # Delete.
    assert client.request("DELETE", f"/calendar/tasks/{tid}", headers=headers).status_code == 200
    assert len(client.get("/calendar/tasks").json()) == 1


def test_today_view(client):
    headers = _auth(client)
    today = dt.date.today().isoformat()
    client.post(
        "/calendar/tasks",
        json={"tasks": [{"title": "Now", "scheduled_date": today, "duration_minutes": 30}]},
        headers=headers,
    )
    data = client.get("/calendar/today").json()
    assert data["date"] == today
    assert data["task_count"] == 1
    assert data["estimated_minutes"] == 30
