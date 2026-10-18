"""Stored thumbnail copies: creation, backfill, the `?w=` route and the cards' `srcset`."""

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.video import Video
from app.services.thumbnails import (
    THUMBNAIL_WIDTHS,
    backfill_video_thumbnails,
    ensure_video_thumbnails,
    thumbnail_variant_path,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


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


def make_video(db, tmp_path, *, width=1280, height=720, key="v1"):
    folder = tmp_path / key
    folder.mkdir()
    thumbnail = folder / "cover.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s={width}x{height}",
            "-frames:v",
            "1",
            str(thumbnail),
        ],
        check=True,
    )
    video = Video(
        yt_video_id=key,
        title=key,
        url=f"https://youtube.com/watch?v={key}",
        folder_path=str(folder),
        thumbnail_path=str(thumbnail),
        audio_path=str(folder / "a.m4a"),
    )
    db.add(video)
    db.commit()
    return video, folder


@needs_ffmpeg
def test_copies_are_created_next_to_the_original_and_smaller(db, tmp_path):
    video, folder = make_video(db, tmp_path)

    assert ensure_video_thumbnails(video)

    sizes = [thumbnail_variant_path(folder, width).stat().st_size for width in THUMBNAIL_WIDTHS]
    assert all(size > 0 for size in sizes)
    assert sizes[0] < sizes[1] < (folder / "cover.jpg").stat().st_size
    # Copies sit in a subfolder: the folder's own files are still only the original.
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == ["cover.jpg"]


@needs_ffmpeg
def test_a_small_original_is_not_upscaled(db, tmp_path):
    video, folder = make_video(db, tmp_path, width=200, height=100)

    ensure_video_thumbnails(video)

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width",
            "-of",
            "csv=p=0",
            str(thumbnail_variant_path(folder, 640)),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "200"


def test_a_missing_ffmpeg_or_file_never_raises(db, tmp_path, monkeypatch):
    video = Video(
        yt_video_id="x",
        title="x",
        url="https://youtube.com/watch?v=x",
        folder_path=str(tmp_path),
        thumbnail_path=str(tmp_path / "missing.jpg"),
    )
    assert ensure_video_thumbnails(video) is False

    (tmp_path / "cover.jpg").write_bytes(b"not an image")
    video.thumbnail_path = str(tmp_path / "cover.jpg")
    monkeypatch.setattr(
        "app.services.thumbnails.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("ffmpeg")),
    )
    assert ensure_video_thumbnails(video) is False


@needs_ffmpeg
def test_backfill_creates_only_the_missing_copies(db, tmp_path):
    first, first_folder = make_video(db, tmp_path, key="a")
    make_video(db, tmp_path, key="b")
    ensure_video_thumbnails(first)

    assert backfill_video_thumbnails(db) == 1
    assert backfill_video_thumbnails(db) == 0


@needs_ffmpeg
def test_route_serves_the_copy_and_falls_back_to_the_original(db, tmp_path):
    video, folder = make_video(db, tmp_path)
    client = TestClient(app)
    original = (folder / "cover.jpg").read_bytes()

    assert (
        client.get(f"/videos/{video.id}/thumbnail?w=320").content == original
    )  # copies not made yet
    ensure_video_thumbnails(video)
    small = client.get(f"/videos/{video.id}/thumbnail?w=320").content
    assert small == thumbnail_variant_path(folder, 320).read_bytes() != original
    assert client.get(f"/videos/{video.id}/thumbnail").content == original
    assert (
        client.get(f"/videos/{video.id}/thumbnail?w=999").content == original
    )  # unknown width: no new file


def test_cards_ask_for_the_small_copies_lazily(db, tmp_path):
    video = Video(
        yt_video_id="c",
        title="Carte",
        url="https://youtube.com/watch?v=c",
        folder_path=str(tmp_path),
        thumbnail_path=str(tmp_path / "c.jpg"),
        audio_path=str(tmp_path / "a.m4a"),
    )
    db.add(video)
    db.commit()

    page = TestClient(app).get("/videos").text

    assert f"/videos/{video.id}/thumbnail?w=320 320w" in page
    assert f"/videos/{video.id}/thumbnail?w=640 640w" in page
    assert 'loading="lazy"' in page
    assert "background-image: url('/videos/" not in page


def test_short_tiles_use_the_original_thumbnail(db, tmp_path):
    channel = Channel(name="Chaine", url="https://youtube.com/@c")
    db.add(channel)
    db.flush()
    video = Video(
        yt_video_id="s",
        title="Short",
        url="https://youtube.com/shorts/s",
        channel_id=channel.id,
        folder_path=str(tmp_path),
        thumbnail_path=str(tmp_path / "s.jpg"),
        audio_path=str(tmp_path / "a.m4a"),
    )
    db.add(video)
    db.commit()

    page = TestClient(app).get(f"/videos?channel_id={channel.id}&section=shorts").text

    assert f'class="video-row-thumb-img" src="/videos/{video.id}/thumbnail" alt=""' in page
    assert "srcset=" not in page
