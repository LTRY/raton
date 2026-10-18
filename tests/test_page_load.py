"""Page load cost: the number of SQL statements of a page must not grow with the library."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video

# Generous: the point is a constant, not the exact figure (a page with one statement per video blows past it).
MAX_STATEMENTS = 60


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
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    session.statements = statements
    yield session
    app.dependency_overrides.pop(get_db, None)


def seed_playbacks(db, video_count: int) -> None:
    channel = Channel(name="Chan", url="https://youtube.com/@chan", yt_channel_id="UC-chan")
    db.add(channel)
    db.flush()
    now = datetime.now(UTC)
    for index in range(video_count):
        video = Video(
            channel_id=channel.id,
            yt_video_id=f"y{index}",
            title=f"Video {index}",
            url=f"https://youtube.com/watch?v={index}",
            folder_path=f"/media/{index}",
            video_path=f"/media/{index}/v.mp4",
        )
        db.add(video)
        db.flush()
        message = json.dumps(
            {
                "type": "playback",
                "action": "Lecture",
                "media_label": "vidéo",
                "position_seconds": 60,
                "duration_seconds": 600,
                "watched_seconds": 60,
                "title": video.title,
            }
        )
        db.add(
            DownloadJob(
                video_id=video.id,
                status="played",
                message=message,
                created_at=now - timedelta(hours=index),
            )
        )
    db.commit()


@pytest.mark.parametrize("path", ["/settings", "/dashboard/historique"])
def test_playback_time_stats_cost_does_not_grow_with_played_videos(db, path):
    seed_playbacks(db, 150)
    db.statements.clear()

    assert TestClient(app).get(path).status_code == 200

    assert len(db.statements) < MAX_STATEMENTS


def seed_followed_library(db, video_count: int) -> None:
    channel = Channel(
        name="Chan",
        url="https://youtube.com/@chan",
        yt_channel_id="UC-chan",
        auto_metadata_enabled=True,
    )
    db.add(channel)
    db.flush()
    for index in range(video_count):
        db.add(
            Video(
                channel_id=channel.id,
                yt_video_id=f"y{index}",
                title=f"Video {index}",
                url=f"https://youtube.com/watch?v={index}",
                folder_path=f"/media/{index}",
                video_path=f"/media/{index}/v.mp4",
                metadata_path=f"/media/{index}/metadata.json",
                duration_seconds=754,
                published_at=datetime.now(UTC) - timedelta(days=index),
            )
        )
    db.commit()


@pytest.mark.parametrize("path", ["/dashboard/nouveautes", "/videos"])
def test_video_cards_do_not_read_metadata_files(db, monkeypatch, path):
    """A metadata.json is the full yt-dlp dump (~140 KB): reading one per card made the pages take seconds."""
    seed_followed_library(db, 12)

    def forbidden(video):
        raise AssertionError(f"metadata.json read while rendering {path}")

    monkeypatch.setattr("app.web.video_library.video_metadata", forbidden)

    response = TestClient(app).get(path)

    assert response.status_code == 200
    assert "12:34" in response.text  # duration_seconds=754, from the column


def seed_playlist(db, video_count: int) -> int:
    from app.models.playlist import Playlist, PlaylistItem

    playlist = Playlist(title="Ma playlist", source="manual")
    db.add(playlist)
    db.flush()
    for index in range(video_count):
        # One channel per video: a lazy `video.channel` load would cost one statement per row.
        channel = Channel(
            name=f"Chan {index}", url=f"https://youtube.com/@c{index}", yt_channel_id=f"UC{index}"
        )
        db.add(channel)
        db.flush()
        video = Video(
            channel_id=channel.id,
            yt_video_id=f"y{index}",
            title=f"Video {index}",
            url=f"https://youtube.com/watch?v={index}",
            folder_path=f"/media/{index}",
            audio_path=f"/media/{index}/a.m4a",
            metadata_path=f"/media/{index}/metadata.json",
            duration_seconds=754,
        )
        db.add(video)
        db.flush()
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=index))
    db.commit()
    return playlist.id


@pytest.mark.parametrize("path", ["/playlists", "/playlists/{id}"])
def test_playlist_pages_read_no_files_and_cost_constant_statements(db, monkeypatch, path):
    playlist_id = seed_playlist(db, 40)

    def forbidden(video):
        raise AssertionError("metadata.json read while rendering a playlist page")

    monkeypatch.setattr("app.web.routes.playlists.video_metadata", forbidden, raising=False)
    db.statements.clear()

    response = TestClient(app).get(path.format(id=playlist_id))

    assert response.status_code == 200
    assert len(db.statements) < 15
    if "{id}" in path:
        assert "12:34" in response.text  # duration_seconds=754, from the column
