import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.setting import AppSetting
from app.models.video import TranscriptStatus, Video
from app.services.channels import media_import, scan_events, scanner, throttle
from app.services.channels.identity import video_already_downloaded
from app.services.channels.scanner import run_scan, scan_channel
from app.services.youtube.downloads import build_video_folder
from app.services.youtube.yt import parse_yt_date


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(
    db: Session,
    channel: Channel,
    folder,
    yt_video_id: str,
    age_days: int,
    rating: int = 0,
    size: int = 10,
) -> Video:
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"x" * size)
    video = Video(
        channel_id=channel.id,
        yt_video_id=yt_video_id,
        title=yt_video_id,
        url=f"https://youtube.com/watch?v={yt_video_id}",
        published_at=datetime.now(UTC) - timedelta(days=age_days),
        downloaded_at=datetime.now(UTC) - timedelta(days=age_days),
        folder_path=str(folder),
        video_path=str(folder / "video.mp4"),
        transcript_status=TranscriptStatus.missing,
        rating=rating,
        file_size_bytes=size,
    )
    db.add(video)
    db.commit()
    return video


def test_video_already_downloaded_detects_existing_video(tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Test")
    db.add(channel)
    db.commit()
    add_video(db, channel, tmp_path / "video", "abc123", 1)

    assert video_already_downloaded(db, "abc123") is True
    assert video_already_downloaded(db, "missing") is False


def test_manual_download_stages_files_before_final_folder(monkeypatch, tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, folder, media_type):
        assert folder.name.startswith(".")
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"video")
        return {
            "id": "manual123",
            "title": "Manual video",
            "webpage_url": url,
        }

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    video = media_import.download_manual_media(db, "https://example.test/video", "video", False)

    final_folder = tmp_path / "Manual channel" / "2026-06-01 - Manual video"
    assert video.channel is not None
    assert video.channel.name == "Manual channel"
    assert video.channel.url == "raton:channel:Manual%20channel"
    assert video.channel.rating == 0
    assert video.folder_path == str(final_folder)
    assert Path(video.video_path).is_file()
    assert final_folder.exists()
    assert not list(tmp_path.glob("Manual channel/.*.download.*"))


def test_manual_download_fetches_sponsorblock_segments_automatically(monkeypatch, tmp_path):
    from app.models.video_sponsor_segment import VideoSponsorSegment

    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor"))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, folder, media_type):
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"video")
        return {"id": "manual123", "title": "Manual video", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    calls = []
    monkeypatch.setattr(
        media_import,
        "fetch_sponsorblock_segments",
        lambda yt_video_id, categories: (
            calls.append((yt_video_id, categories))
            or [{"category": "sponsor", "start_seconds": 5.0, "end_seconds": 15.0}]
        ),
    )

    video = media_import.download_manual_media(db, "https://example.test/video", "video", False)

    assert calls == [("manual123", ["sponsor"])]
    rows = list(
        db.scalars(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
    )
    assert len(rows) == 1
    assert rows[0].source == "sponsorblock"


def test_manual_download_ignores_sponsorblock_failures(monkeypatch, tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual456",
            "title": "Manual video 2",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, folder, media_type):
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"video")
        return {"id": "manual456", "title": "Manual video 2", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    def fail(*args, **kwargs):
        raise RuntimeError("SponsorBlock down")

    monkeypatch.setattr(media_import, "fetch_sponsorblock_segments", fail)

    # Must not raise even though SponsorBlock fails — the download itself succeeds regardless.
    video = media_import.download_manual_media(db, "https://example.test/video2", "video", False)

    assert video.id is not None


def test_manual_download_rolls_back_session_when_replace_sponsor_segments_fails(
    monkeypatch, tmp_path
):
    from app.models.video_sponsor_segment import VideoSponsorSegment

    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor"))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual789",
            "title": "Manual video 3",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, folder, media_type):
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"video")
        return {"id": "manual789", "title": "Manual video 3", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)
    monkeypatch.setattr(
        media_import,
        "fetch_sponsorblock_segments",
        lambda yt_video_id, categories: [
            {"category": "sponsor", "start_seconds": 1.0, "end_seconds": 2.0}
        ],
    )

    def fake_replace(db, video_id, source, segments):
        # Fails *inside* replace_video_sponsor_segments's own write (after it has
        # already touched the session), unlike test_manual_download_ignores_sponsorblock_failures
        # above, which only fails inside fetch_sponsorblock_segments before any DB write.
        # A NOT NULL violation on commit mirrors a real mid-transaction DB error and
        # leaves the session's transaction unusable until it is rolled back.
        db.add(
            VideoSponsorSegment(
                video_id=video_id, category=None, start_seconds=1.0, end_seconds=2.0, source=source
            )
        )
        db.commit()

    monkeypatch.setattr(media_import, "replace_video_sponsor_segments", fake_replace)

    # Must not raise even though the sponsor-segment write itself fails mid-commit.
    video = media_import.download_manual_media(db, "https://example.test/video3", "video", False)

    assert video.id is not None
    assert (
        db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
        is None
    )

    # The session must not be left in a "pending rollback" state — a later commit
    # (as run_manual_download_job performs afterward for job-status bookkeeping)
    # must succeed rather than raise.
    db.add(DownloadJob(status="downloaded", message="follow-up commit works"))
    db.commit()


def test_manual_download_can_replace_metadata_only_record(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Manual channel")
    folder = tmp_path / "Manual channel" / "2026-06-01 - Manual video"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text("{}", encoding="utf-8")
    video = Video(
        channel=channel,
        yt_video_id="manual123",
        title="Manual video",
        url="https://example.test/video",
        media_type="metadata",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        metadata_path=str(folder / "metadata.json"),
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=2,
    )
    db.add_all([channel, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "video.mp4").write_bytes(b"video")
        return {
            "id": "manual123",
            "title": "Manual video",
            "webpage_url": url,
            "upload_date": "20260601",
        }

    monkeypatch.setattr(media_import, "download_media", fake_download_media)
    monkeypatch.setattr(media_import, "download_subtitles", lambda url, folder, **kwargs: None)

    updated = media_import.download_manual_media(db, "https://example.test/video", "video", False)

    assert updated.id == video.id
    assert updated.media_type == "video"
    assert Path(updated.video_path).is_file()
    assert Path(updated.metadata_path).is_file()


def test_manual_download_preserves_existing_short_url(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Manual channel")
    folder = tmp_path / "Manual channel" / "2026-06-01 - Manual short"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text("{}", encoding="utf-8")
    video = Video(
        channel=channel,
        yt_video_id="short123",
        title="Manual short",
        url="https://www.youtube.com/shorts/short123",
        media_type="metadata",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        metadata_path=str(folder / "metadata.json"),
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=2,
    )
    db.add_all([channel, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "short123",
            "title": "Manual short",
            "channel": "Manual channel",
            "webpage_url": "https://www.youtube.com/watch?v=short123",
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "video.mp4").write_bytes(b"video")
        return {
            "id": "short123",
            "title": "Manual short",
            "webpage_url": "https://www.youtube.com/watch?v=short123",
            "upload_date": "20260601",
        }

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    updated = media_import.download_manual_media(
        db, "https://www.youtube.com/watch?v=short123", "video", False
    )

    assert updated.id == video.id
    assert updated.url == "https://www.youtube.com/shorts/short123"
    assert Path(updated.video_path).is_file()


def test_manual_download_canonicalizes_new_short_url(monkeypatch, tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "short123",
            "title": "Manual short",
            "channel": "Manual channel",
            "webpage_url": "https://www.youtube.com/watch?v=short123",
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "video.mp4").write_bytes(b"video")
        return {
            "id": "short123",
            "title": "Manual short",
            "webpage_url": "https://www.youtube.com/watch?v=short123",
            "upload_date": "20260601",
        }

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    video = media_import.download_manual_media(
        db, "https://www.youtube.com/shorts/short123", "video", False
    )

    assert video.url == "https://www.youtube.com/shorts/short123"
    assert Path(video.video_path).is_file()


def test_manual_download_can_add_audio_to_existing_video(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "Manual channel" / "2026-06-01 - Manual video"
    folder.mkdir(parents=True)
    video_file = folder / "video.mp4"
    video_file.write_bytes(b"video")
    video = Video(
        yt_video_id="manual123",
        title="Manual video",
        url="https://example.test/video",
        media_type="video",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        video_path=str(video_file),
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=5,
    )
    db.add_all([video, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        assert media_type == "audio"
        staging.mkdir(parents=True)
        (staging / "audio.mp3").write_bytes(b"audio")
        return {"id": "manual123", "title": "Manual video", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    updated = media_import.download_manual_media(db, "https://example.test/video", "audio", False)

    assert updated.id == video.id
    assert updated.media_type == "video"
    assert Path(updated.video_path).is_file()
    assert Path(updated.audio_path).is_file()
    assert Path(updated.video_path).read_bytes() == b"video"
    assert updated.file_size_bytes >= len(b"videoaudio")


def test_manual_download_can_add_video_to_existing_audio(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "Manual channel" / "2026-06-01 - Manual video"
    folder.mkdir(parents=True)
    audio_file = folder / "audio.mp3"
    audio_file.write_bytes(b"audio")
    video = Video(
        yt_video_id="manual123",
        title="Manual video",
        url="https://example.test/video",
        media_type="audio",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        audio_path=str(audio_file),
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=5,
    )
    db.add_all([video, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        assert media_type == "video"
        staging.mkdir(parents=True)
        (staging / "video.mp4").write_bytes(b"video")
        return {"id": "manual123", "title": "Manual video", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    updated = media_import.download_manual_media(db, "https://example.test/video", "video", False)

    assert updated.id == video.id
    assert updated.media_type == "video"
    assert Path(updated.video_path).is_file()
    assert Path(updated.audio_path).is_file()
    assert Path(updated.audio_path).read_bytes() == b"audio"
    assert updated.file_size_bytes >= len(b"audiovideo")


def test_import_video_metadata_writes_metadata_and_transcript_without_media(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Manual channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "meta123",
            "title": "Metadata only",
            "webpage_url": url,
            "upload_date": "20260601",
            "duration": 120,
            "view_count": 42,
        },
    )

    def fail_download_media(*args, **kwargs):
        raise AssertionError("media download should not run")

    def fake_download_subtitles(url, folder, **kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "subtitle.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n",
            encoding="utf-8",
        )

    def fake_download_thumbnail(url, folder, **kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "thumbnail.webp").write_bytes(b"thumbnail")

    monkeypatch.setattr(media_import, "download_media", fail_download_media)
    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)
    monkeypatch.setattr(media_import, "download_thumbnail", fake_download_thumbnail)

    video = media_import.import_video_metadata(db, "https://example.test/video", channel.id)

    assert video.media_type == "metadata"
    assert video.video_path is None
    assert Path(video.thumbnail_path).is_file()
    assert Path(video.metadata_path).is_file()
    assert Path(video.transcript_path).read_text(encoding="utf-8") == "Bonjour"
    assert video.file_size_bytes > 0


def test_import_video_metadata_adopts_existing_folder_without_video_row(monkeypatch, tmp_path):
    """A folder left on disk after its `videos` row was deleted is re-linked, media included."""
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Orphan channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    info = {
        "id": "orphan123",
        "title": "Orphan video",
        "webpage_url": "https://example.test/video",
        "upload_date": "20260601",
    }
    monkeypatch.setattr(media_import, "extract_video_info", lambda url: info)
    folder = build_video_folder(tmp_path, channel.name, "Orphan video", parse_yt_date("20260601"))
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"video")
    (folder / "audio.mp3").write_bytes(b"audio")
    (folder / "thumbnail.webp").write_bytes(b"thumbnail")
    (folder / "subtitle.fr.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n", encoding="utf-8"
    )

    def fail_download(*args, **kwargs):
        raise AssertionError("nothing should be downloaded again")

    monkeypatch.setattr(media_import, "download_subtitles", fail_download)
    monkeypatch.setattr(media_import, "download_thumbnail", fail_download)

    video = media_import.import_video_metadata(db, "https://example.test/video", channel.id)

    assert Path(video.folder_path) == folder
    assert video.media_type == "video"
    assert Path(video.video_path).read_bytes() == b"video"
    assert Path(video.audio_path).read_bytes() == b"audio"
    assert Path(video.metadata_path).is_file()
    assert Path(video.transcript_path).read_text(encoding="utf-8") == "Bonjour"
    assert video.file_size_bytes >= len(b"videoaudio")
    assert (folder / "video.mp4").is_file()


def test_import_video_metadata_canonicalizes_short_urls(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Meta channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "short123",
            "title": "Short metadata",
            "webpage_url": "https://www.youtube.com/watch?v=short123",
            "upload_date": "20260601",
        },
    )
    monkeypatch.setattr(media_import, "download_subtitles", lambda url, folder, **kwargs: None)
    monkeypatch.setattr(
        media_import,
        "download_thumbnail",
        lambda url, folder, **kwargs: (
            folder.mkdir(parents=True, exist_ok=True),
            (folder / "thumbnail.webp").write_bytes(b"thumbnail"),
        ),
    )

    video = media_import.import_video_metadata(
        db,
        "https://www.youtube.com/watch?v=short123",
        channel.id,
        source_section="shorts",
    )

    assert video.url == "https://www.youtube.com/shorts/short123"


def test_scan_channel_imports_only_metadata_for_new_videos(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(
        url="https://example.test/channel",
        name="Auto channel",
        category_labels="science,maker",
    )
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    monkeypatch.setattr(
        scanner,
        "list_channel_entries",
        lambda channel, page=1, page_size=25, section="videos": [
            {
                "id": "auto123",
                "title": "Flat metadata",
                "url": "https://example.test/watch/auto123",
            }
        ],
    )
    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "auto123",
            "title": "Auto metadata",
            "webpage_url": url,
            "upload_date": "20260601",
            "duration": 90,
            "view_count": 1000,
            "description": "Full video metadata",
        },
    )

    def fail_download_media(*args, **kwargs):
        raise AssertionError("scan should not download media")

    def fake_download_subtitles(url, folder, **kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "subtitle.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n",
            encoding="utf-8",
        )

    def fake_download_thumbnail(url, folder, **kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "thumbnail.webp").write_bytes(b"thumbnail")

    monkeypatch.setattr(media_import, "download_media", fail_download_media)
    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)
    monkeypatch.setattr(media_import, "download_thumbnail", fake_download_thumbnail)

    imported = scan_channel(db, channel)
    video = db.query(Video).filter_by(yt_video_id="auto123").one()

    assert imported == 1
    assert video.media_type == "metadata"
    assert video.download_source == "auto"
    assert video.category_labels == "science,maker"
    assert video.title == "Auto metadata"
    assert video.video_path is None
    assert Path(video.thumbnail_path).is_file()
    assert Path(video.metadata_path).is_file()
    assert "Full video metadata" in Path(video.metadata_path).read_text(encoding="utf-8")
    assert Path(video.transcript_path).is_file()


def test_scan_channel_stops_when_known_video_is_reached(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    existing = Video(
        yt_video_id="known123",
        title="Known video",
        url="https://example.test/watch/known123",
        media_type="metadata",
        folder_path=str(tmp_path / "known"),
        transcript_status=TranscriptStatus.missing,
        channel=channel,
    )
    db.add(channel)
    db.add(existing)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    requested_pages = []

    def fake_list_channel_entries(channel, page=1, page_size=25, section="videos"):
        requested_pages.append(page)
        if page == 1:
            return [
                {
                    "id": "new123",
                    "title": "New metadata",
                    "url": "https://example.test/watch/new123",
                },
                {
                    "id": "known123",
                    "title": "Known video",
                    "url": "https://example.test/watch/known123",
                },
            ]
        raise AssertionError("scan should stop before requesting older pages")

    monkeypatch.setattr(scanner, "list_channel_entries", fake_list_channel_entries)
    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "new123",
            "title": "New metadata",
            "webpage_url": url,
            "upload_date": "20260602",
        },
    )
    monkeypatch.setattr(media_import, "download_subtitles", lambda url, folder, **kwargs: None)
    monkeypatch.setattr(
        media_import,
        "download_thumbnail",
        lambda url, folder, **kwargs: (
            folder.mkdir(parents=True, exist_ok=True),
            (folder / "thumbnail.webp").write_bytes(b"thumbnail"),
        ),
    )

    imported = scan_channel(db, channel, max_pages=3)

    assert imported == 1
    assert requested_pages == [1]
    assert db.query(Video).filter_by(yt_video_id="new123").one()


def test_scan_channel_shorts_repairs_existing_watch_urls(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    existing = Video(
        yt_video_id="short123",
        title="Known short",
        url="https://www.youtube.com/watch?v=short123",
        media_type="metadata",
        folder_path=str(tmp_path / "known-short"),
        transcript_status=TranscriptStatus.missing,
        channel=channel,
    )
    db.add(channel)
    db.add(existing)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()

    requested_pages = []

    def fake_list_channel_entries(channel, page=1, page_size=25, section="videos"):
        requested_pages.append((page, section))
        return [
            {"id": "short123", "title": "Known short", "url": "https://example.test/watch/short123"}
        ]

    monkeypatch.setattr(scanner, "list_channel_entries", fake_list_channel_entries)

    imported = scanner.scan_channel_section(db, channel, max_pages=1, section="shorts")

    assert imported == 0
    assert requested_pages == [(1, "shorts")]
    assert existing.url == "https://www.youtube.com/shorts/short123"


def test_scheduled_scan_stops_when_less_than_twenty_percent_quota_is_free(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="global_quota_bytes", value="100"))
    db.commit()
    add_video(db, channel, tmp_path / "large", "large", 1, size=81)

    def fail_scan_channel(*args, **kwargs):
        raise AssertionError("scheduled scan should stop before scanning channels")

    monkeypatch.setattr(scanner, "scan_channel", fail_scan_channel)

    result = run_scan(db, enforce_storage_headroom=True)

    assert result == {"status": "storage_low", "downloaded": 0, "deleted": 0}
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "skipped"))
    assert job is not None
    assert "moins de 20%" in job.message


def test_retry_transcript_download_prefers_french(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    folder = tmp_path / "video"
    video = add_video(db, channel, folder, "retryfr", 1)

    def fake_download_subtitles(url, staging, languages=None, **kwargs):
        if languages == ["fr"]:
            (staging / "Titre.fr.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n",
                encoding="utf-8",
            )
        elif languages == ["en"]:
            (staging / "Titre.en.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)

    result = media_import.retry_transcript_download(db, video, languages=["fr", "en"])

    assert result.transcript_status == TranscriptStatus.downloaded
    assert Path(result.transcript_path).read_text(encoding="utf-8") == "Bonjour"
    assert Path(result.subtitle_path).name == "Titre.fr.vtt"
    assert Path(result.subtitle_path).parent == folder


def test_retry_transcript_download_falls_back_to_english_when_french_missing(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    folder = tmp_path / "video"
    video = add_video(db, channel, folder, "retryen", 1)

    def fake_download_subtitles(url, staging, languages=None, **kwargs):
        if languages == ["en"]:
            (staging / "Titre.en.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)

    result = media_import.retry_transcript_download(db, video, languages=["fr", "en"])

    assert result.transcript_status == TranscriptStatus.downloaded
    assert Path(result.transcript_path).read_text(encoding="utf-8") == "Hello"
    assert Path(result.subtitle_path).name == "Titre.en.vtt"


def test_retry_transcript_download_raises_when_no_subtitles_available(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    folder = tmp_path / "video"
    video = add_video(db, channel, folder, "retrynone", 1)

    monkeypatch.setattr(
        media_import, "download_subtitles", lambda url, staging, languages=None, **kwargs: None
    )

    with pytest.raises(ValueError):
        media_import.retry_transcript_download(db, video)

    assert video.transcript_status == TranscriptStatus.missing
    assert video.transcript_path is None
    leftover = [p for p in folder.parent.iterdir() if p.name != folder.name]
    assert leftover == []


def test_retry_transcript_download_replaces_differently_named_stale_subtitle(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    folder = tmp_path / "video"
    video = add_video(db, channel, folder, "retrystale", 1)
    stale_subtitle = folder / "AncienTitre.fr.vtt"
    stale_subtitle.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nAncien\n", encoding="utf-8")
    video.subtitle_path = str(stale_subtitle)
    video.transcript_status = TranscriptStatus.failed
    db.commit()

    def fake_download_subtitles(url, staging, languages=None, **kwargs):
        if languages == ["fr"]:
            (staging / "NouveauTitre.fr.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nNouveau\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)

    result = media_import.retry_transcript_download(db, video, languages=["fr", "en"])

    assert result.transcript_status == TranscriptStatus.downloaded
    assert Path(result.transcript_path).read_text(encoding="utf-8") == "Nouveau"
    subtitle_files = [p for p in folder.iterdir() if p.suffix == ".vtt"]
    assert [p.name for p in subtitle_files] == ["NouveauTitre.fr.vtt"]


def test_manual_redownload_resets_watched_at_so_purge_keeps_new_file(monkeypatch, tmp_path):
    from app.services.media.media_storage import purge_watched_media

    db = make_session()
    folder = tmp_path / "Manual channel" / "2026-06-01 - Manual video"
    folder.mkdir(parents=True)
    video = Video(
        yt_video_id="manual123",
        title="Manual video",
        url="https://example.test/video",
        media_type="metadata",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, tzinfo=UTC),
        folder_path=str(folder),
        watched_at=datetime.now(UTC) - timedelta(days=30),
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=0,
    )
    db.add_all([video, AppSetting(key="media_root", value=str(tmp_path))])
    db.commit()

    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {
            "id": "manual123",
            "title": "Manual video",
            "channel": "Manual channel",
            "webpage_url": url,
            "upload_date": "20260601",
        },
    )

    def fake_download_media(url, staging, media_type):
        staging.mkdir(parents=True)
        (staging / "video.mp4").write_bytes(b"video")
        return {"id": "manual123", "title": "Manual video", "webpage_url": url}

    monkeypatch.setattr(media_import, "download_media", fake_download_media)

    updated = media_import.download_manual_media(db, "https://example.test/video", "video", False)

    assert updated.watched_at is None
    assert purge_watched_media(db) == 0
    assert Path(updated.video_path).is_file()


def _entries(count, prefix="vid"):
    return [
        {
            "id": f"{prefix}{i}",
            "title": f"Video {i}",
            "url": f"https://example.test/watch/{prefix}{i}",
        }
        for i in range(count)
    ]


def _fake_import(imported_ids, fail_on=None):
    def fake(db, video_url, channel_id=None, preview=None, **kwargs):
        if fail_on and preview["id"] == fail_on:
            raise throttle.RateLimitedError("HTTP Error 429: Too Many Requests")
        video = Video(
            yt_video_id=preview["id"],
            title=preview["title"],
            url=video_url,
            media_type="metadata",
            folder_path=f"/tmp/{preview['id']}",
            transcript_status=TranscriptStatus.missing,
            channel_id=channel_id,
        )
        db.add(video)
        db.commit()
        imported_ids.append(preview["id"])
        return video

    return fake


def test_scan_channel_section_caps_imports_and_keeps_the_backlog_for_the_next_scan(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    known = Video(
        yt_video_id="known",
        title="Known",
        url="https://example.test/watch/known",
        media_type="metadata",
        folder_path="/tmp/known",
        transcript_status=TranscriptStatus.missing,
        channel=channel,
    )
    db.add_all([channel, known])
    db.commit()
    # Newest first, then the one video already known.
    feed = _entries(5) + [
        {"id": "known", "title": "Known", "url": "https://example.test/watch/known"}
    ]
    monkeypatch.setattr(
        scanner,
        "list_channel_entries",
        lambda channel, page=1, page_size=25, section="videos": feed if page == 1 else [],
    )
    imported_ids = []
    monkeypatch.setattr(scanner, "import_video_metadata", _fake_import(imported_ids))

    first = scan_channel(db, channel, max_imports=2)
    second = scan_channel(db, channel, max_imports=2)
    third = scan_channel(db, channel, max_imports=2)

    # Oldest first, so what is left is still newer than the first known video.
    assert (first, second, third) == (2, 2, 1)
    assert imported_ids == ["vid4", "vid3", "vid2", "vid1", "vid0"]


def test_scan_channel_section_stops_between_two_imports_when_asked(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.commit()
    monkeypatch.setattr(
        scanner,
        "list_channel_entries",
        lambda channel, page=1, page_size=25, section="videos": _entries(5) if page == 1 else [],
    )
    imported_ids = []
    monkeypatch.setattr(scanner, "import_video_metadata", _fake_import(imported_ids))
    monkeypatch.setattr(scanner, "pause_between_imports", lambda: None)

    imported = scanner.scan_channel_section(
        db, channel, max_pages=1, should_stop=lambda: len(imported_ids) >= 2
    )

    assert imported == 2
    assert imported_ids == ["vid0", "vid1"]


def test_scan_channel_section_raises_on_rate_limit_and_keeps_what_was_imported(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.commit()
    monkeypatch.setattr(
        scanner,
        "list_channel_entries",
        lambda channel, page=1, page_size=25, section="videos": _entries(4) if page == 1 else [],
    )
    imported_ids = []
    monkeypatch.setattr(
        scanner, "import_video_metadata", _fake_import(imported_ids, fail_on="vid1")
    )

    with pytest.raises(throttle.RateLimitedError):
        scan_channel(db, channel, max_imports=10)

    # vid3 and vid2 went through (oldest first), vid1 was refused and nothing after it was tried.
    assert imported_ids == ["vid3", "vid2"]
    failed = db.scalar(select(DownloadJob).where(DownloadJob.status == "failed"))
    assert failed is not None and "429" in failed.message


def test_scan_channel_section_shorts_stop_at_a_page_without_new_shorts(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.add_all(
        Video(
            yt_video_id=f"s{i}",
            title="Short",
            url=f"https://www.youtube.com/shorts/s{i}",
            media_type="metadata",
            folder_path=f"/tmp/s{i}",
            transcript_status=TranscriptStatus.missing,
            channel=channel,
        )
        for i in range(2)
    )
    db.commit()
    requested = []

    def fake_list(channel, page=1, page_size=25, section="videos"):
        requested.append(page)
        return _entries(2, prefix="s")

    monkeypatch.setattr(scanner, "list_channel_entries", fake_list)

    imported = scanner.scan_channel_section(db, channel, max_pages=3, section="shorts")

    assert imported == 0
    assert requested == [1]


def test_run_scan_stops_at_the_first_rate_limit(monkeypatch):
    db = make_session()
    first = Channel(url="https://example.test/a", name="A", auto_metadata_enabled=True)
    second = Channel(url="https://example.test/b", name="B", auto_metadata_enabled=True)
    db.add_all([first, second])
    db.commit()
    scanned = []

    def fake_scan(db, channel, **kwargs):
        scanned.append(channel.id)
        raise throttle.RateLimitedError("HTTP Error 429")

    monkeypatch.setattr(scanner, "scan_channel", fake_scan)

    result = run_scan(db)

    assert result == {"status": "rate_limited", "downloaded": 0, "deleted": 0}
    assert scanned == [first.id]


def test_import_video_metadata_reuses_the_extracted_info_for_subtitles_and_thumbnail(
    monkeypatch, tmp_path
):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()
    extracted = {
        "id": "once123",
        "title": "Once",
        "webpage_url": "https://example.test/watch/once123",
        "upload_date": "20260601",
    }
    monkeypatch.setattr(media_import, "extract_video_info", lambda url: extracted)
    received = []
    monkeypatch.setattr(
        media_import,
        "download_subtitles",
        lambda url, folder, **kwargs: received.append(kwargs["info"]),
    )
    monkeypatch.setattr(
        media_import,
        "download_thumbnail",
        lambda url, folder, **kwargs: received.append(kwargs["info"]),
    )

    media_import.import_video_metadata(
        db,
        "https://example.test/watch/once123",
        channel.id,
        preview={"id": "once123", "title": "Flat"},
    )

    assert received == [extracted, extracted]


def test_import_video_metadata_keeps_going_when_a_subtitle_request_gets_429(monkeypatch, tmp_path):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()
    monkeypatch.setattr(
        media_import,
        "extract_video_info",
        lambda url: {"id": "lim123", "title": "Limited", "upload_date": "20260601"},
    )

    def refused(*args, **kwargs):
        raise RuntimeError(
            "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
        )

    monkeypatch.setattr(media_import, "download_subtitles", refused)
    monkeypatch.setattr(media_import, "download_thumbnail", lambda url, folder, **kwargs: None)

    video = media_import.import_video_metadata(db, "https://example.test/watch/lim123", channel.id)

    # The video exists (without transcript) and the scan is not asked to stop.
    assert video.transcript_status == TranscriptStatus.missing
    warning = db.scalar(select(DownloadJob).where(DownloadJob.status == "warning"))
    assert warning is not None and "429" in warning.message


def test_run_scan_visits_least_recently_scanned_channels_first_and_records_it(monkeypatch):
    db = make_session()
    now = datetime.now(UTC)
    never = Channel(url="https://example.test/never", name="Never", auto_metadata_enabled=True)
    old = Channel(
        url="https://example.test/old",
        name="Old",
        auto_metadata_enabled=True,
        last_scanned_at=now - timedelta(days=3),
    )
    recent = Channel(
        url="https://example.test/recent",
        name="Recent",
        auto_metadata_enabled=True,
        last_scanned_at=now - timedelta(hours=1),
    )
    db.add_all([recent, old, never])
    db.commit()
    order = []
    monkeypatch.setattr(
        scanner, "scan_channel", lambda db, channel, **kwargs: order.append(channel.name) or 0
    )

    run_scan(db)

    assert order == ["Never", "Old", "Recent"]
    db.refresh(never)
    assert never.last_scanned_at is not None


def test_run_scan_resumes_at_the_channel_a_rate_limit_stopped_on(monkeypatch):
    db = make_session()
    first = Channel(url="https://example.test/a", name="A", auto_metadata_enabled=True)
    second = Channel(url="https://example.test/b", name="B", auto_metadata_enabled=True)
    third = Channel(url="https://example.test/c", name="C", auto_metadata_enabled=True)
    db.add_all([first, second, third])
    db.commit()
    blocked = {"B"}

    def fake_scan(db, channel, **kwargs):
        if channel.name in blocked:
            raise throttle.RateLimitedError("HTTP Error 429")
        return 0

    monkeypatch.setattr(scanner, "scan_channel", fake_scan)

    assert run_scan(db)["status"] == "rate_limited"
    blocked.clear()
    order = []
    monkeypatch.setattr(
        scanner, "scan_channel", lambda db, channel, **kwargs: order.append(channel.name) or 0
    )
    run_scan(db)

    # A was done, B was cut short and C never reached: B and C come before A the next night.
    assert order == ["B", "C", "A"]


def test_run_scan_waits_long_between_channels_only_after_an_import(monkeypatch):
    db = make_session()
    db.add_all(
        Channel(url=f"https://example.test/{name}", name=name, auto_metadata_enabled=True)
        for name in ("a", "b", "c")
    )
    db.commit()
    imports = {"a": 2, "b": 0, "c": 0}
    monkeypatch.setattr(
        scanner, "scan_channel", lambda db, channel, **kwargs: imports[channel.name]
    )
    monkeypatch.setattr(throttle, "PAUSE_BETWEEN_CHANNELS", (10.0, 30.0))
    monkeypatch.setattr(throttle, "PAUSE_AFTER_LISTING_ONLY", (1.0, 3.0))
    pauses = []
    monkeypatch.setattr(scanner, "pause", pauses.append)

    run_scan(db)

    # After "a" (imported 2) the long pause, after "b" (nothing new) the short one.
    assert pauses == [(10.0, 30.0), (1.0, 3.0)]


def test_run_scan_emits_progress_events_ending_with_a_final_one(monkeypatch):
    db = make_session()
    db.add(Channel(url="https://example.test/a", name="Alpha", auto_metadata_enabled=True))
    db.commit()
    monkeypatch.setattr(scanner, "scan_channel", lambda db, channel, **kwargs: 3)

    run_scan(db)

    events, _ = scan_events.events_after(0)
    messages = [event["message"] for event in events]
    assert messages[0].startswith("Scan démarré")
    assert any("Alpha" in message for message in messages)
    assert events[-1]["final"] is True and "3 fiche(s)" in events[-1]["message"]
    assert [event["final"] for event in events[:-1]] == [False] * (len(events) - 1)


def test_scan_channel_section_logs_a_scheduled_premiere_as_scheduled_not_failed(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.commit()
    monkeypatch.setattr(
        scanner,
        "list_channel_entries",
        lambda channel, page=1, page_size=25, section="videos": _entries(2) if page == 1 else [],
    )

    def fake_import(db_, video_url, channel_id=None, preview=None, **kwargs):
        if preview["id"] == "vid1":
            raise RuntimeError("ERROR: [youtube] vid1: Premieres in 3 hours")
        return _fake_import([])(db_, video_url, channel_id=channel_id, preview=preview)

    monkeypatch.setattr(scanner, "import_video_metadata", fake_import)

    imported = scan_channel(db, channel)

    assert imported == 1
    assert db.scalar(select(DownloadJob).where(DownloadJob.status == "failed")) is None
    scheduled = db.scalar(select(DownloadJob).where(DownloadJob.status == "scheduled"))
    assert scheduled is not None and "pas encore disponible" in scheduled.message
    events, _ = scan_events.events_after(0)
    assert not any(event["level"] == "error" for event in events)


def test_retry_transcript_download_without_language_takes_the_original_track_once(
    monkeypatch, tmp_path
):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    video = add_video(db, channel, tmp_path / "video", "retryorig", 1)
    calls = []

    def fake_download_subtitles(url, staging, languages=None, **kwargs):
        calls.append(languages)
        (staging / "Titre.ar-orig.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nمرحبا\n", encoding="utf-8"
        )

    monkeypatch.setattr(media_import, "download_subtitles", fake_download_subtitles)

    result = media_import.retry_transcript_download(db, video)

    # languages=None lets download_subtitles pick the track itself: one attempt, no fr/en loop.
    assert calls == [None]
    assert result.transcript_status == TranscriptStatus.downloaded


def _missing_video_with_metadata(db, channel, tmp_path, yt_video_id, metadata):
    folder = tmp_path / yt_video_id
    video = add_video(db, channel, folder, yt_video_id, 1)
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    video.metadata_path = str(folder / "metadata.json")
    video.transcript_status = TranscriptStatus.missing
    db.commit()
    return video


def test_backfill_original_transcripts_only_retries_videos_that_have_an_original_track(
    monkeypatch, tmp_path
):
    from app.services.rag import transcript_backfill

    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    with_track = _missing_video_with_metadata(
        db, channel, tmp_path, "withtrack", {"automatic_captions": {"ar-orig": [], "fr": []}}
    )
    _missing_video_with_metadata(
        db, channel, tmp_path, "notrack", {"automatic_captions": {}, "subtitles": {}}
    )
    _missing_video_with_metadata(
        db, channel, tmp_path, "onlytranslations", {"automatic_captions": {"fr": [], "en": []}}
    )
    retried = []
    monkeypatch.setattr(
        transcript_backfill,
        "retry_transcript_download",
        lambda db_, video: retried.append(video.yt_video_id),
    )

    assert transcript_backfill.backfill_original_transcripts(db) == 1
    assert retried == [with_track.yt_video_id]

    # Done once: the next startup does not look again.
    assert transcript_backfill.backfill_original_transcripts(db) == 0
    assert retried == [with_track.yt_video_id]


def test_backfill_original_transcripts_stops_after_repeated_failures_and_resumes_later(
    monkeypatch, tmp_path
):
    from app.services.rag import transcript_backfill

    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    db.add(channel)
    db.commit()
    for index in range(8):
        _missing_video_with_metadata(
            db, channel, tmp_path, f"v{index}", {"automatic_captions": {"fr-orig": []}}
        )
    attempts = []

    def failing(db_, video):
        attempts.append(video.yt_video_id)
        raise ValueError("boom")

    monkeypatch.setattr(transcript_backfill, "retry_transcript_download", failing)

    assert transcript_backfill.backfill_original_transcripts(db) == 0
    assert len(attempts) == transcript_backfill.MAX_CONSECUTIVE_FAILURES

    # Not marked done: it is tried again at the next startup.
    monkeypatch.setattr(transcript_backfill, "retry_transcript_download", lambda db_, video: None)
    assert transcript_backfill.backfill_original_transcripts(db) == 8
