"""The players report every 30 s while a media plays: the back keeps one row per listening."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.users import default_user
from back.services.videos import playback
from back.services.videos.playback import (
    PLAYBACK_MERGE_WINDOW,
    latest_playback_positions,
    record_playback_activity,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(db, yt_id="abc"):
    video = Video(
        yt_video_id=yt_id,
        title="Titre",
        url=f"https://www.youtube.com/watch?v={yt_id}",
        folder_path=f"/media/{yt_id}",
    )
    db.add(video)
    db.commit()
    return video


def report(db, user, video, media="video", position=10.0, watched=30.0):
    return record_playback_activity(db, user.id, video, media, position, 600.0, watched)


def test_reports_of_one_listening_become_one_row_with_the_seconds_added_up():
    db = make_session()
    user, video = default_user(db), add_video(db)

    first = report(db, user, video, position=1, watched=30)  # "Lecture"
    second = report(db, user, video, position=40, watched=30)
    third = report(db, user, video, position=75, watched=12)

    assert first.id == second.id == third.id
    assert db.query(DownloadJob).filter_by(status="played").count() == 1
    view = playback.playback_activity_view(db.get(DownloadJob, first.id))
    assert view["watched_seconds"] == 72
    assert view["position_seconds"] == 75
    assert view["action"] == "Lecture"  # how the listening began, not how the last report did


def test_a_report_after_a_pause_longer_than_the_window_starts_a_new_row():
    db = make_session()
    user, video = default_user(db), add_video(db)
    first = report(db, user, video)
    first.created_at = datetime.now(UTC) - PLAYBACK_MERGE_WINDOW - timedelta(seconds=5)
    db.commit()

    second = report(db, user, video, position=100)

    assert second.id != first.id
    assert db.query(DownloadJob).filter_by(status="played").count() == 2


def test_audio_and_video_of_a_fiche_stay_apart():
    db = make_session()
    user, video = default_user(db), add_video(db)

    report(db, user, video, media="video")
    report(db, user, video, media="audio")

    assert db.query(DownloadJob).filter_by(status="played").count() == 2


def test_two_users_do_not_share_a_row():
    db = make_session()
    video = add_video(db)
    first = default_user(db)
    from back.services.common.users import create_user

    other = create_user(db, "Autre")

    report(db, first, video)
    report(db, other, video)

    assert db.query(DownloadJob).filter_by(status="played").count() == 2


def test_the_resume_position_is_the_latest_report():
    db = make_session()
    user, video = default_user(db), add_video(db)

    report(db, user, video, position=10)
    report(db, user, video, position=95)

    assert latest_playback_positions(db, user.id, video.id)["video"]["position_seconds"] == 95
