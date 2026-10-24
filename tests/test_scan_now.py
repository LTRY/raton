"""The "Lancer le scan maintenant" button of /settings: `/api/scan` and the event feed it polls."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.services.ingest import scan_events, scanner
from back.services.jobs import scheduler


@pytest.fixture
def client():
    # The scan routes read nothing in the DB, but the couvre-feu guard of every `/api` route does.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = lambda: sessionmaker(bind=engine)()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_scan_now_starts_the_scan_in_the_background(client, monkeypatch):
    started = []
    monkeypatch.setattr("back.api.scan.run_manual_scan_job", lambda: started.append(True))

    response = client.post("/api/scan")

    assert response.status_code == 202
    assert response.json() == {"after": 0}
    assert started == [True]
    events, _ = scan_events.events_after(0)
    assert events[0]["message"] == "Scan lancé à la demande."


def test_scan_now_refuses_when_a_scan_is_already_running(client):
    assert scanner.scan_lock.acquire(blocking=False)
    try:
        response = client.post("/api/scan")
    finally:
        scanner.scan_lock.release()

    assert response.status_code == 409
    assert response.json() == {"detail": "Un scan est déjà en cours."}


def test_scan_events_feed_returns_only_newer_events_and_running_flag(client):
    scan_events.emit("un")
    scan_events.emit("deux", "error", final=True)

    response = client.get("/api/scan/events?after=1")

    payload = response.json()
    assert [event["message"] for event in payload["events"]] == ["deux"]
    assert payload["events"][0]["level"] == "error" and payload["events"][0]["final"] is True
    assert payload["last_id"] == 2
    assert payload["running"] is False


def test_failed_manual_scan_ends_the_feed_with_a_final_error(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(scheduler, "scheduled_scan", boom)

    scheduler.run_manual_scan_job()

    events, _ = scan_events.events_after(0)
    assert events[-1]["final"] is True and events[-1]["level"] == "error"
    assert "db down" in events[-1]["message"]
