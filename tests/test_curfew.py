"""Couvre-feu: the hours, the API it closes, and the Historique left open for commentaires."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.video import Video
from back.services.common.curfew import CURFEW_TIMEZONE, read_curfew
from back.services.common.settings import save_settings
from back.services.common.user_state import video_state
from back.services.videos import playback
from tests.users import add_user, user_id


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


def paris(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 24, hour, minute, tzinfo=CURFEW_TIMEZONE)


def start_curfew_now(db) -> None:
    """A couvre-feu around the current time, whatever time the test runs at."""
    now = datetime.now(CURFEW_TIMEZONE)
    save_settings(
        db,
        user_id(db),
        curfew_enabled=True,
        curfew_start=(now - timedelta(hours=1)).strftime("%H:%M"),
        curfew_end=(now + timedelta(hours=1)).strftime("%H:%M"),
    )


def add_played_video(db) -> Video:
    channel = Channel(name="Chaîne", url="https://youtube.com/@c", yt_channel_id="UC-c")
    video = Video(
        channel=channel,
        yt_video_id="v1",
        title="Vidéo du soir",
        url="https://youtube.com/watch?v=v1",
        folder_path="/media/v1",
        media_type="video",
    )
    db.add(video)
    db.commit()
    playback.record_playback_activity(db, user_id(db), video, "video", 12, 120, 12)
    return video


@pytest.mark.parametrize(
    ("start", "end", "now", "active"),
    [
        ("22:00", "10:00", paris(23), True),
        ("22:00", "10:00", paris(3), True),
        ("22:00", "10:00", paris(22), True),
        ("22:00", "10:00", paris(10), False),
        ("22:00", "10:00", paris(15), False),
        ("01:00", "06:00", paris(3), True),
        ("01:00", "06:00", paris(7), False),
        ("22:00", "22:00", paris(22), False),
    ],
)
def test_curfew_range_may_span_midnight(db, start, end, now, active):
    save_settings(db, user_id(db), curfew_enabled=True, curfew_start=start, curfew_end=end)

    assert read_curfew(db, user_id(db), now).active is active


def test_curfew_ends_at_its_next_end_time(db):
    save_settings(db, user_id(db), curfew_enabled=True, curfew_start="22:00", curfew_end="10:00")

    assert read_curfew(db, user_id(db), paris(23)).ends_at == paris(10) + timedelta(days=1)
    assert read_curfew(db, user_id(db), paris(3)).ends_at == paris(10)


def test_curfew_is_off_by_default_and_when_disabled(db):
    assert read_curfew(db, user_id(db), paris(23)).active is False
    save_settings(db, user_id(db), curfew_enabled=False, curfew_start="22:00", curfew_end="10:00")
    assert read_curfew(db, user_id(db), paris(23)).active is False


def test_settings_refuse_a_curfew_hour_that_is_not_hh_mm(db):
    response = TestClient(app).put("/api/settings", json={"curfew_start": "25:00"})

    assert response.status_code == 422
    assert "HH:MM" in response.json()["detail"]


def test_settings_store_the_curfew(db):
    response = TestClient(app).put(
        "/api/settings",
        json={"curfew_enabled": True, "curfew_start": "9:30", "curfew_end": "11:00"},
    )

    assert response.json()["curfew"] | {"active": None, "ends_at": None} == {
        "enabled": True,
        "start": "09:30",
        "end": "11:00",
        "active": None,
        "ends_at": None,
    }


def test_curfew_closes_the_api_but_the_home_the_historique_and_the_commentaire(db):
    video = add_played_video(db)
    start_curfew_now(db)
    client = TestClient(app)

    refused = client.get("/api/library")
    assert refused.status_code == 423
    assert "Couvre-feu" in refused.json()["detail"]
    assert client.get(f"/api/videos/{video.id}/video").status_code == 423
    assert client.put("/api/settings", json={"curfew_enabled": False}).status_code == 423

    assert client.get("/api/curfew").json()["active"] is True
    # The home page: Raton, the library chat and its discussions, the user menu.
    for path in ("/api/settings", "/api/chat", "/api/users"):
        assert client.get(path).status_code == 200, path
    assert client.post("/api/raton/visit").status_code == 200
    history = client.get("/api/historique").json()
    assert history["rows"][0]["video"]["title"] == "Vidéo du soir"
    saved = client.put(f"/api/videos/{video.id}/comment", json={"comment": "À revoir"})
    assert saved.status_code == 200
    assert video_state(db, user_id(db), video.id).comment == "À revoir"


def test_curfew_pages_show_the_couvre_feu_and_the_historique_writes_commentaires(db, front_client):
    video = add_played_video(db)
    start_curfew_now(db)
    site = front_client(db)

    closed = site.get("/channels")
    assert closed.status_code == 423
    assert "Couvre-feu" in closed.text
    assert 'href="/dashboard/historique"' in closed.text
    assert 'href="/settings"' not in closed.text

    home = site.get("/")
    assert home.status_code == 200
    assert "data-chat" in home.text or "chat-bar" in home.text
    assert 'href="/dashboard/historique"' in home.text
    assert "Écrire dans l’historique" in home.text
    assert 'href="/settings"' not in home.text

    history = site.get("/dashboard/historique").text
    assert f'action="/videos/{video.id}/comment"' in history
    assert f'href="/videos/{video.id}"' not in history
    assert 'href="/settings"' not in history

    saved = site.post(
        f"/videos/{video.id}/comment",
        data={"comment": "Idée du soir", "next": "/dashboard/historique"},
        follow_redirects=False,
    )
    assert saved.headers["location"] == "/dashboard/historique"
    assert video_state(db, user_id(db), video.id).comment == "Idée du soir"


def test_historique_is_the_normal_page_outside_the_curfew(db, front_client):
    video = add_played_video(db)
    history = front_client(db).get("/dashboard/historique").text

    assert f'href="/videos/{video.id}"' in history
    assert f'action="/videos/{video.id}/comment"' not in history


def test_curfew_is_each_users_own(db):
    other = add_user(db, "Camille")
    start_curfew_now(db)
    client = TestClient(app)

    assert client.get("/api/library").status_code == 423
    assert client.get("/api/library", headers={"X-Raton-User": str(other.id)}).status_code == 200
    assert read_curfew(db, other.id).enabled is False
