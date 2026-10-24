from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.user_state import blank_video_state
from back.services.media.media_storage import purge_watched_media
from back.services.videos.playback import mark_watched_if_complete
from tests.users import add_user, set_video_state


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(
    db, folder, *, watched_days_ago=None, rating=0, video_file=True, audio_file=False, size=10
):
    """Create a video row with real files under `folder`."""
    channel = db.query(Channel).first()
    if channel is None:
        channel = Channel(url="https://example.test/channel", name="Chaîne test")
        db.add(channel)
        db.commit()
    folder.mkdir(parents=True)
    video_path = audio_path = None
    if video_file:
        (folder / "video.mp4").write_bytes(b"v" * size)
        video_path = str(folder / "video.mp4")
    if audio_file:
        (folder / "audio.m4a").write_bytes(b"a" * size)
        audio_path = str(folder / "audio.m4a")
    (folder / "transcript.txt").write_text("transcript")
    video = Video(
        channel_id=channel.id,
        yt_video_id=folder.name,
        title=folder.name,
        url=f"https://youtube.com/watch?v={folder.name}",
        folder_path=str(folder),
        video_path=video_path,
        audio_path=audio_path,
        transcript_path=str(folder / "transcript.txt"),
        file_size_bytes=size,
        watched_at=None
        if watched_days_ago is None
        else datetime.now(UTC) - timedelta(days=watched_days_ago),
    )
    db.add(video)
    db.commit()
    if rating:
        set_video_state(db, video, rating=rating)
    return video


def test_video_watched_at_defaults_to_none(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid")

    assert video.watched_at is None


def test_mark_watched_requires_ninety_percent(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid")
    state = blank_video_state(1, video.id)

    assert mark_watched_if_complete(video, state, 89, 100) is False
    assert video.watched_at is None and state.watched_at is None
    assert mark_watched_if_complete(video, state, 90, 100) is True
    assert video.watched_at is not None
    assert state.watched_at == video.watched_at


def test_mark_watched_never_overwrites_first_date(tmp_path):
    db = make_session()
    first = datetime(2026, 1, 1, tzinfo=UTC)
    video = add_video(db, tmp_path / "vid")
    video.watched_at = first
    state = blank_video_state(1, video.id)
    state.watched_at = first

    assert mark_watched_if_complete(video, state, 100, 100) is False
    assert video.watched_at == first and state.watched_at == first


def test_a_second_user_watching_keeps_the_purge_countdown_of_the_first(tmp_path):
    db = make_session()
    first = datetime(2026, 1, 1, tzinfo=UTC)
    video = add_video(db, tmp_path / "vid")
    video.watched_at = first
    other = blank_video_state(2, video.id)

    # Vu for the second user too, but the shared files still go 7 days after the first Vu.
    assert mark_watched_if_complete(video, other, 100, 100) is True
    assert other.watched_at > first
    assert video.watched_at == first


def test_mark_watched_ignores_unknown_duration(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid")
    state = blank_video_state(1, video.id)

    assert mark_watched_if_complete(video, state, 50, 0) is False
    assert video.watched_at is None


def test_purge_deletes_both_formats_after_seven_days_and_keeps_the_rest(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid", watched_days_ago=8, audio_file=True)

    assert purge_watched_media(db) == 1

    db.refresh(video)
    assert video.video_path is None and video.audio_path is None
    assert not (tmp_path / "vid" / "video.mp4").exists()
    assert not (tmp_path / "vid" / "audio.m4a").exists()
    assert (tmp_path / "vid" / "transcript.txt").exists()
    assert video.transcript_path is not None
    assert video.file_size_bytes == len("transcript")
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "purged"))
    assert job is not None and job.video_id == video.id


def test_purge_keeps_recently_watched_unwatched_and_archived(tmp_path):
    db = make_session()
    recent = add_video(db, tmp_path / "recent", watched_days_ago=6)
    unwatched = add_video(db, tmp_path / "unwatched")
    archived = add_video(db, tmp_path / "archived", watched_days_ago=30, rating=4)
    five = add_video(db, tmp_path / "five", watched_days_ago=30, rating=5)

    assert purge_watched_media(db) == 0

    for video in (recent, unwatched, archived, five):
        db.refresh(video)
        assert video.video_path is not None
        assert (tmp_path / video.yt_video_id / "video.mp4").exists()


def test_purge_keeps_a_video_any_user_rated_four_or_more(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid", watched_days_ago=30, rating=1)
    set_video_state(db, video, add_user(db, "Invité").id, rating=4)

    assert purge_watched_media(db) == 0
    db.refresh(video)
    assert video.video_path is not None


def test_purge_purges_when_rating_dropped_below_archive_threshold(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid", watched_days_ago=30, rating=3)

    assert purge_watched_media(db) == 1
    db.refresh(video)
    assert video.video_path is None


def test_purge_ignores_videos_without_files(tmp_path):
    db = make_session()
    add_video(db, tmp_path / "vid", watched_days_ago=30, video_file=False)

    assert purge_watched_media(db) == 0
    assert db.scalar(select(DownloadJob).where(DownloadJob.status == "purged")) is None


def test_purge_refuses_path_outside_video_folder(tmp_path):
    db = make_session()
    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"precious")
    video = add_video(db, tmp_path / "vid", watched_days_ago=30)
    video.audio_path = str(outside)
    db.commit()

    # The video file is removed, the tampered audio path is refused and logged.
    assert purge_watched_media(db) == 0

    assert outside.exists()
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "failed"))
    assert job is not None and job.video_id == video.id


def test_mark_watched_rejects_non_finite_values(tmp_path):
    db = make_session()
    video = add_video(db, tmp_path / "vid")

    for position, duration in [
        (float("nan"), 100),
        (50, float("nan")),
        (float("inf"), 100),
        (50, float("inf")),
        (float("inf"), float("inf")),
    ]:
        assert (
            mark_watched_if_complete(video, blank_video_state(1, video.id), position, duration)
            is False
        )
        assert video.watched_at is None
