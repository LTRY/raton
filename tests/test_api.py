"""`/api` routes: pagination, fiche detail, French error details, stats and recent jobs."""

import json
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
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment

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
        ("get", "/api/videos/999", "Vidéo introuvable"),
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


def test_api_video_detail_returns_the_fiche_as_raw_values(db, tmp_path):
    folder = tmp_path / "fiche"
    folder.mkdir()
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "description": "Desc",
                "tags": ["a", ""],
                "chapters": [{"title": "Intro", "start_time": 125.5}, {"start_time": 3}],
                "duration": 3725,
                "view_count": "1234",
                "like_count": "beaucoup",
                "channel": "Chan",
            }
        ),
        encoding="utf-8",
    )
    (folder / "transcript.txt").write_text("Le transcript.", encoding="utf-8")
    (folder / "transcript.notes.txt").write_text("# Notes", encoding="utf-8")
    (folder / "transcript.chat.json").write_text(
        json.dumps([{"role": "user", "content": "Salut"}, {"role": "system", "content": "x"}]),
        encoding="utf-8",
    )
    video = Video(
        yt_video_id="v",
        title="Fiche",
        url="https://youtube.com/watch?v=v",
        folder_path=str(folder),
        metadata_path=str(folder / "metadata.json"),
        transcript_path=str(folder / "transcript.txt"),
        audio_path=str(folder / "a.m4a"),
        is_new=True,
    )
    db.add(video)
    db.flush()
    playlist = Playlist(title="Écoute", source="manual")
    db.add(playlist)
    db.flush()
    db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=1))
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=10,
            end_seconds=40,
            source="sponsorblock",
        )
    )
    db.commit()

    response = TestClient(app).get(f"/api/videos/{video.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Fiche"
    assert payload["is_new"] is True
    assert payload["media_urls"] == {
        "video": None,
        "audio": f"/videos/{video.id}/audio",
        "thumbnail": None,
        "subtitles": None,
    }
    assert payload["metadata"] == {
        "description": "Desc",
        "tags": ["a"],
        "chapters": [{"title": "Intro", "start_seconds": 125.5}],
        "duration_seconds": 3725.0,
        "view_count": 1234,
        "like_count": None,
        "comment_count": None,
        "uploader": "Chan",
    }
    assert payload["documents"] == {
        "transcript": "Le transcript.",
        "notes": "# Notes",
        "short_summary": None,
        "suggested_questions": [],
        "chat_messages": [{"role": "user", "content": "Salut"}],
    }
    assert payload["sponsor_segments"] == [
        {"category": "sponsor", "start_seconds": 10.0, "end_seconds": 40.0}
    ]
    assert payload["skip_segments"] == [{"start": 10.0, "end": 40.0}]
    assert payload["sponsor_skip_enabled"] is True
    assert payload["resume_positions"] == {}
    assert payload["playlists"] == [
        {
            "playlist_id": playlist.id,
            "title": "Écoute",
            "item_id": payload["playlists"][0]["item_id"],
        }
    ]


def test_api_video_detail_leaves_the_fiche_in_nouveautes(db):
    add_videos(db, add_channel(db, "Chan"), 1, "v")
    video = db.query(Video).one()
    video.is_new = True
    db.commit()

    TestClient(app).get(f"/api/videos/{video.id}")

    db.refresh(video)
    assert video.is_new is True
