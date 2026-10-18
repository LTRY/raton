"""The "Lancer le scan maintenant" button of /settings: start route and the event feed it polls."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import scan_events, scanner
from app.web.routes import settings as settings_routes


@pytest.fixture
def client():
    return TestClient(app)


def test_scan_now_starts_the_scan_in_the_background(client, monkeypatch):
    started = []
    monkeypatch.setattr(settings_routes, "run_scan_now_job", lambda: started.append(True))

    response = client.post("/settings/scan", headers={"x-requested-with": "fetch"})

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert started == [True]
    events, _ = scan_events.events_after(0)
    assert events[0]["message"] == "Scan lancé à la demande."


def test_scan_now_refuses_when_a_scan_is_already_running(client):
    assert scanner.scan_lock.acquire(blocking=False)
    try:
        response = client.post("/settings/scan", headers={"x-requested-with": "fetch"})
    finally:
        scanner.scan_lock.release()

    assert response.status_code == 409
    assert response.json()["status"] == "already_running"


def test_scan_events_feed_returns_only_newer_events_and_running_flag(client):
    scan_events.emit("un")
    scan_events.emit("deux", "error", final=True)

    response = client.get("/settings/scan/events?after=1")

    payload = response.json()
    assert [event["message"] for event in payload["events"]] == ["deux"]
    assert payload["events"][0]["level"] == "error" and payload["events"][0]["final"] is True
    assert payload["last_id"] == 2
    assert payload["running"] is False


def test_failed_manual_scan_ends_the_feed_with_a_final_error(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(settings_routes, "scheduled_scan", boom)

    settings_routes.run_scan_now_job()

    events, _ = scan_events.events_after(0)
    assert events[-1]["final"] is True and events[-1]["level"] == "error"
    assert "db down" in events[-1]["message"]
