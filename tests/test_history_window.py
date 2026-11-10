"""The Historique and the resume position read a bounded slice of `download_jobs`, which gets a
row per playback report and only grows."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.users import default_user
from back.services.videos import playback
from back.services.videos.history import HISTORY_WINDOW_DAYS, history_page

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)(), engine


def report(position: float, media_label: str = "vidéo") -> str:
    return json.dumps(
        {
            "type": "playback",
            "action": "Lecture",
            "media_label": media_label,
            "position_seconds": position,
            "duration_seconds": 600,
            "watched_seconds": 30,
            "title": "Titre",
        },
        ensure_ascii=False,
    )


def test_the_historique_only_lists_its_window():
    db, _ = make_session()
    user = default_user(db)
    for days_ago in (1, HISTORY_WINDOW_DAYS - 1, HISTORY_WINDOW_DAYS + 5):
        db.add(
            DownloadJob(
                status="played",
                message=report(60),
                user_id=user.id,
                created_at=NOW - timedelta(days=days_ago),
                # No fiche: each report is told apart by its own job.
            )
        )
    db.commit()

    page = history_page(db, user.id, now=NOW)

    assert [row.day for row in page.rows] == [
        (NOW - timedelta(days=1)).date(),
        (NOW - timedelta(days=HISTORY_WINDOW_DAYS - 1)).date(),
    ]


def test_the_last_position_of_each_media_comes_from_the_newest_reports(monkeypatch):
    db, _ = make_session()
    user = default_user(db)
    video = Video(
        yt_video_id="abc",
        title="Titre",
        url="https://www.youtube.com/watch?v=abc",
        folder_path="/media/abc",
    )
    db.add(video)
    db.commit()
    monkeypatch.setattr(playback, "POSITION_REPORTS_SCANNED", 3)
    # Oldest first: an old audio report, then more video reports than the scan reads.
    reports = [report(10, "audio"), report(1), report(2), report(3), report(4)]
    for index, message in enumerate(reports):
        db.add(
            DownloadJob(
                status="played",
                message=message,
                user_id=user.id,
                video_id=video.id,
                created_at=NOW + timedelta(minutes=index),
            )
        )
    db.commit()

    positions = playback.latest_playback_positions(db, user.id, video.id)

    assert positions["video"]["position_seconds"] == 4
    assert "audio" not in positions


def test_download_jobs_carry_the_indexes_the_playback_readers_use():
    _, engine = make_session()
    indexed = {
        tuple(index["column_names"]) for index in inspect(engine).get_indexes("download_jobs")
    }

    assert ("user_id", "status", "created_at") in indexed
    assert ("video_id",) in indexed
