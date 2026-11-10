"""A day starts and ends in the users' time zone, whatever the clock of the container (UTC)."""

import re
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.job import DownloadJob
from back.services.common.local_time import LOCAL_TIMEZONE, local_datetime, local_now
from back.services.common.users import default_user
from back.services.videos.history import history_page
from back.services.videos.playback import playback_time_stats, recent_played_jobs

ROOT = Path(__file__).resolve().parents[1]
# 00:30 in Paris on July 4th (UTC+2), still July 3rd in UTC.
JUST_AFTER_MIDNIGHT = datetime(2026, 7, 3, 22, 30, tzinfo=UTC)
PLAYBACK = (
    '{"type": "playback", "action": "Lecture", "media_label": "vidéo", "position_seconds": 60,'
    ' "duration_seconds": 600, "watched_seconds": 60, "title": "Titre"}'
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_local_now_is_in_the_users_time_zone():
    assert local_now().tzinfo is LOCAL_TIMEZONE


def test_a_naive_date_from_the_database_is_utc():
    assert local_datetime(datetime(2026, 7, 3, 22, 30)) == JUST_AFTER_MIDNIGHT
    assert local_datetime(datetime(2026, 7, 3, 22, 30)).date() == date(2026, 7, 4)


def test_a_playback_after_local_midnight_counts_for_the_new_day():
    db = make_session()
    user = default_user(db)
    db.add(
        DownloadJob(
            status="played", message=PLAYBACK, user_id=user.id, created_at=JUST_AFTER_MIDNIGHT
        )
    )
    db.commit()
    now = datetime(2026, 7, 4, 0, 45, tzinfo=LOCAL_TIMEZONE)

    history = history_page(db, user.id, now=now)
    stats = playback_time_stats(recent_played_jobs(db, user.id, now), now)

    assert history.today == date(2026, 7, 4)
    assert [row.day for row in history.rows] == [date(2026, 7, 4)]
    assert stats["today"]["video"]["seconds"] == 60


def test_no_code_reads_the_clock_of_the_machine_as_the_users():
    """`datetime.now().astimezone()` is the container's time zone: use `local_now()`."""
    machine_clock = re.compile(r"datetime\.now\(\)\s*\.astimezone\(\)")
    offenders = [
        str(path.relative_to(ROOT))
        for folder in ("back", "front")
        for path in (ROOT / folder).rglob("*.py")
        if machine_clock.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
