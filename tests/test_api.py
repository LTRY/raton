"""`/api` routes: pagination, French error details, stats and recent jobs."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video

NOW = datetime(2026, 10, 9, tzinfo=UTC)


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


def add_channel(db, name):
    channel = Channel(name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}")
    db.add(channel)
    db.flush()
    return channel


def add_videos(db, channel, count, prefix):
    for index in range(count):
        db.add(
            Video(
                channel_id=channel.id,
                yt_video_id=f"{prefix}{index}",
                title=f"{prefix}{index}",
                url=f"https://youtube.com/watch?v={prefix}{index}",
                folder_path=f"/media/{prefix}{index}",
                downloaded_at=NOW + timedelta(minutes=index),
            )
        )
    db.commit()


def test_api_videos_are_paginated_newest_first(db):
    add_videos(db, add_channel(db, "Chan"), 55, "v")
    client = TestClient(app)

    first = client.get("/api/videos").json()
    assert (first["page"], first["total_pages"], first["total"]) == (1, 2, 55)
    assert len(first["items"]) == 50
    assert first["items"][0]["title"] == "v54"

    second = client.get("/api/videos?page=2").json()
    assert second["page"] == 2
    assert [item["title"] for item in second["items"]] == ["v4", "v3", "v2", "v1", "v0"]


def test_api_videos_page_past_the_end_returns_the_last_page(db):
    add_videos(db, add_channel(db, "Chan"), 3, "v")

    payload = TestClient(app).get("/api/videos?page=9").json()

    assert payload["page"] == 1
    assert payload["total_pages"] == 1
    assert len(payload["items"]) == 3


def test_api_videos_filters_by_channel(db):
    add_videos(db, add_channel(db, "A"), 2, "a")
    other = add_channel(db, "B")
    add_videos(db, other, 3, "b")

    payload = TestClient(app).get(f"/api/videos?channel_id={other.id}").json()

    assert payload["total"] == 3
    assert {item["channel_id"] for item in payload["items"]} == {other.id}


def test_api_videos_rejects_page_zero(db):
    assert TestClient(app).get("/api/videos?page=0").status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "detail"),
    [
        ("post", "/api/channels/999/rating?rating=3", "Chaîne introuvable"),
        ("delete", "/api/channels/999", "Chaîne introuvable"),
        ("post", "/api/videos/999/rating?rating=3", "Vidéo introuvable"),
        ("get", "/api/videos/999/sponsor-segments", "Vidéo introuvable"),
    ],
)
def test_api_not_found_details_are_french(db, method, path, detail):
    response = getattr(TestClient(app), method)(path)

    assert response.status_code == 404
    assert response.json() == {"detail": detail}


def test_api_stats_counts_the_library(db):
    add_videos(db, add_channel(db, "Chan"), 2, "v")

    payload = TestClient(app).get("/api/stats").json()

    assert payload["channels"] == 1
    assert payload["videos"] == 2
    assert set(payload) == {"channels", "videos", "used_bytes", "quota_bytes"}


def test_api_errors_lists_the_hundred_newest_jobs(db):
    for index in range(105):
        db.add(DownloadJob(status="failed", message=f"m{index}", created_at=NOW + timedelta(index)))
    db.commit()

    payload = TestClient(app).get("/api/errors").json()

    assert len(payload) == 100
    assert payload[0]["message"] == "m104"
    assert payload[-1]["message"] == "m5"
