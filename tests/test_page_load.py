"""Page load cost: the number of SQL statements of a page must not grow with the library."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from tests.site import site_client

# Generous: the point is a constant, not the exact figure (a page with one statement per video blows past it).
# Each `/api` call of a page also costs the couvre-feu guard's one read of its settings.
MAX_STATEMENTS = 70


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

    assert site_client().get(path).status_code == 200

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


def forbid_metadata_reads(db, monkeypatch, tmp_path) -> None:
    """Give every fiche a real metadata.json, then fail on any read of one.

    The files must exist: a reader checks `is_file()` first, so a missing file would hide a read.
    """
    for video in db.query(Video):
        path = tmp_path / str(video.id) / "metadata.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
        video.metadata_path = str(path)
    db.commit()
    read_text = Path.read_text

    def guarded(self, *args, **kwargs):
        if self.name == "metadata.json":
            raise AssertionError(f"{self} read while rendering a list")
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)


@pytest.mark.parametrize("path", ["/dashboard/nouveautes", "/videos"])
def test_video_cards_do_not_read_metadata_files(db, monkeypatch, tmp_path, path):
    """A metadata.json is the full yt-dlp dump (~140 KB): reading one per card made the pages take seconds."""
    seed_followed_library(db, 12)
    forbid_metadata_reads(db, monkeypatch, tmp_path)

    response = site_client().get(path)

    assert response.status_code == 200
    assert "12:34" in response.text  # duration_seconds=754, from the column


def seed_playlist(db, video_count: int) -> int:
    from back.models.playlist import Playlist, PlaylistItem

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
def test_playlist_pages_read_no_files_and_cost_constant_statements(db, monkeypatch, tmp_path, path):
    playlist_id = seed_playlist(db, 40)
    forbid_metadata_reads(db, monkeypatch, tmp_path)
    db.statements.clear()

    response = site_client().get(path.format(id=playlist_id))

    assert response.status_code == 200
    assert len(db.statements) < 15
    if "{id}" in path:
        assert "12:34" in response.text  # duration_seconds=754, from the column


def test_playlists_page_cost_does_not_grow_with_the_playlists(db):
    # Each playlist's cover must come from the one batched query, not from a load per playlist.
    from back.models.playlist import Playlist, PlaylistItem

    def add_playlist(index: int) -> None:
        video = Video(
            yt_video_id=f"cover{index}",
            title=f"Cover {index}",
            url=f"https://youtube.com/watch?v=cover{index}",
            folder_path=f"/media/cover{index}",
            thumbnail_path=f"/media/cover{index}/thumb.jpg",
        )
        playlist = Playlist(title=f"Playlist {index}", source="manual")
        db.add_all([video, playlist])
        db.flush()
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=1))
        db.commit()

    add_playlist(0)
    db.expunge_all()
    db.statements.clear()
    site_client().get("/playlists")
    one = len(db.statements)
    for index in range(1, 8):
        add_playlist(index)
    db.expunge_all()
    db.statements.clear()

    response = site_client().get("/playlists")

    assert response.status_code == 200
    assert response.text.count("/thumbnail?w=320") == 8
    assert len(db.statements) == one
