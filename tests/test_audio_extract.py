import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.setting import AppSetting
from app.models.video import TranscriptStatus, Video
from app.services.channels import scanner
from app.services.media import audio_extract

MERGED = {
    "requested_formats": [
        {"vcodec": "avc1.640028", "acodec": "none"},
        {"vcodec": "none", "acodec": "mp4a.40.2"},
    ]
}
PROGRESSIVE = {"requested_formats": [{"vcodec": "avc1.64001F", "acodec": "mp4a.40.2"}]}


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_downloaded_video(db, tmp_path, info: dict | None) -> Video:
    folder = tmp_path / "Chan" / "2026-06-01 - Title"
    folder.mkdir(parents=True)
    video_file = folder / "title.mp4"
    video_file.write_bytes(b"video")
    metadata = folder / "metadata.json"
    if info is not None:
        metadata.write_text(json.dumps(info), encoding="utf-8")
    video = Video(
        yt_video_id="abc123",
        title="Title",
        url="https://www.youtube.com/watch?v=abc123",
        media_type="video",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        video_path=str(video_file),
        metadata_path=str(metadata) if info is not None else None,
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=5,
    )
    db.add_all([video, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()
    return video


def fake_copy(source: Path, target: Path) -> bool:
    target.write_bytes(b"audio")
    return True


def forbid_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("yt-dlp must not be called")

    monkeypatch.setattr(scanner, "extract_video_info", refuse)
    monkeypatch.setattr(scanner, "download_media", refuse)


def test_dedicated_audio_stream_is_detected(tmp_path):
    merged, progressive = tmp_path / "merged.json", tmp_path / "progressive.json"
    merged.write_text(json.dumps(MERGED), encoding="utf-8")
    progressive.write_text(json.dumps(PROGRESSIVE), encoding="utf-8")

    assert audio_extract.video_audio_is_dedicated_stream(merged) is True
    assert audio_extract.video_audio_is_dedicated_stream(progressive) is False
    assert audio_extract.video_audio_is_dedicated_stream(tmp_path / "missing.json") is False


def test_audio_is_copied_out_of_a_merged_video_without_yt_dlp(monkeypatch, tmp_path):
    db = make_session()
    video = make_downloaded_video(db, tmp_path, MERGED)
    forbid_network(monkeypatch)
    monkeypatch.setattr(scanner, "copy_audio_track", fake_copy)

    updated = scanner.download_manual_media(db, video.url, "audio", False)

    assert updated.id == video.id
    assert Path(updated.audio_path).name == "title.m4a"
    assert Path(updated.audio_path).read_bytes() == b"audio"
    assert Path(updated.video_path).read_bytes() == b"video"
    assert updated.media_type == "video"


def test_degraded_progressive_track_is_downloaded_with_yt_dlp(monkeypatch, tmp_path):
    db = make_session()
    video = make_downloaded_video(db, tmp_path, PROGRESSIVE)
    monkeypatch.setattr(scanner, "copy_audio_track", lambda *a: pytest.fail("must not extract"))
    monkeypatch.setattr(
        scanner,
        "extract_video_info",
        lambda url: {"id": "abc123", "title": "Title", "channel": "Chan", "webpage_url": url},
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "audio.m4a").write_bytes(b"dedicated")
        return {"id": "abc123", "title": "Title", "webpage_url": url}

    monkeypatch.setattr(scanner, "download_media", fake_download_media)

    updated = scanner.download_manual_media(db, video.url, "audio", False)

    assert Path(updated.audio_path).read_bytes() == b"dedicated"


def test_ffmpeg_failure_falls_back_to_yt_dlp(monkeypatch, tmp_path):
    db = make_session()
    video = make_downloaded_video(db, tmp_path, MERGED)
    monkeypatch.setattr(scanner, "copy_audio_track", lambda source, target: False)
    monkeypatch.setattr(
        scanner,
        "extract_video_info",
        lambda url: {"id": "abc123", "title": "Title", "channel": "Chan", "webpage_url": url},
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "audio.m4a").write_bytes(b"dedicated")
        return {"id": "abc123", "title": "Title", "webpage_url": url}

    monkeypatch.setattr(scanner, "download_media", fake_download_media)

    updated = scanner.download_manual_media(db, video.url, "audio", False)

    assert Path(updated.audio_path).read_bytes() == b"dedicated"
    assert not list(Path(video.folder_path).glob("*.partial*"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_copy_audio_track_fails_cleanly_on_a_file_without_audio(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    target = tmp_path / "out" / "broken.m4a"

    assert audio_extract.copy_audio_track(source, target) is False
    assert not target.exists()
    assert not list((tmp_path / "out").glob("*.partial*"))
