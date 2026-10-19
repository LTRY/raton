"""`/videos` filters, sort and pagination run in SQL; they must agree with the Python twins and stay cheap."""

import itertools
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.video import Video
from app.services.youtube.view_counts import backfill_view_counts
from app.web.shared import LIBRARY_PAGE_SIZE
from app.web.video_library import video_filters_condition, video_matches_filters


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
    session.statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: session.statements.append(args[2]))
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_video(db, key, channel=None, **fields):
    defaults = dict(
        channel_id=channel.id if channel else None,
        yt_video_id=key,
        title=f"Video {key}",
        url=f"https://youtube.com/watch?v={key}",
        folder_path=f"/media/{key}",
    )
    video = Video(**{**defaults, **fields})
    db.add(video)
    db.flush()
    return video


def test_sql_filters_match_the_python_twin(db):
    channel = Channel(
        name="Chan",
        url="https://youtube.com/@c",
        yt_channel_id="UC1",
        category_labels="musique,live",
    )
    db.add(channel)
    db.flush()
    variants = [
        dict(),
        dict(video_path="/m/v.mp4"),
        dict(audio_path="/m/a.m4a", transcript_path="/m/t.txt"),
        dict(metadata_path="/m/metadata.json", rating=4),
        dict(media_type="metadata", imported_via_form=True),
        dict(url="https://youtube.com/shorts/s1", video_path="/m/s.mp4", category_labels="musique"),
        dict(category_labels="podcast,musique", list_state="hidden"),
        dict(category_labels="", video_path=""),
        dict(category_labels="humour", rating=2, audio_path="/m/a.m4a", list_state="watched"),
    ]
    for index, fields in enumerate(variants):
        # Video 7 has no labels of its own and inherits the channel's, as `ensure_video_channel` persists it.
        add_video(db, f"v{index}", channel if index % 2 == 0 else None, **fields)
    db.commit()
    kinds = ["audio", "shorts", "transcript"]
    labels = ["musique", "live"]
    modes = ["or", "and", "not"]

    def sql_ids(args):
        statement = (
            select(Video)
            .outerjoin(Channel, Video.channel_id == Channel.id)
            .where(video_filters_condition(*args))
        )
        return {video.id for video in db.scalars(statement)}

    cases = [
        (
            asset_filters,
            category_filters,
            excluded_assets,
            excluded_categories,
            rated,
            asset_mode,
            category_mode,
            hide,
            uncategorized,
        )
        for asset_filters, category_filters, excluded_assets, excluded_categories, rated, hide, uncategorized in (
            itertools.product(
                [set(), {"audio"}, {"audio", "video"}, set(kinds)],
                [set(), {"musique"}, set(labels)],
                [set(), {"shorts"}],
                [set(), {"podcast"}],
                [False, True],
                [False, True],
                [False, True],
            )
        )
        for asset_mode, category_mode in itertools.product(modes, modes)
    ]
    # Videos without labels of their own inherit their channel's on the fly...
    before = [sql_ids(args) for args in cases]
    # ...and `ensure_video_channel` persists that copy when they are displayed: same answers either way.
    for video in db.scalars(select(Video)):
        if not video.category_labels and video.channel and video.channel.category_labels:
            video.category_labels = video.channel.category_labels
    db.commit()
    videos = list(db.scalars(select(Video)))
    for args, ids_before in zip(cases, before, strict=True):
        expected = {
            video.id
            for video in videos
            if video_matches_filters(
                video, *args[:7], hide_hidden=args[7], uncategorized_only=args[8]
            )
        }
        assert ids_before == expected == sql_ids(args), args


def test_videos_page_paginates_in_sql_and_sorts_by_stored_view_count(db):
    now = datetime.now(UTC)
    for index in range(LIBRARY_PAGE_SIZE + 5):
        add_video(
            db,
            f"p{index}",
            audio_path=f"/m/{index}.m4a",
            downloaded_at=now - timedelta(minutes=index),
            view_count=index,
        )
    db.commit()
    db.statements.clear()

    page = TestClient(app).get("/videos?sort=views&page=2")

    assert page.status_code == 200
    # Page 2 holds the 5 least viewed videos, most viewed first.
    titles = list(dict.fromkeys(re.findall(r"Video p\d+", page.text)))
    assert titles == ["Video p4", "Video p3", "Video p2", "Video p1", "Video p0"]
    assert len(db.statements) < 30


def test_backfill_reads_view_counts_from_metadata_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.youtube.view_counts.local_media_path", lambda path: Path(path)
    )
    counted = tmp_path / "counted.json"
    counted.write_text(json.dumps({"view_count": 1234, "duration": 754.0}))
    bare = tmp_path / "bare.json"
    bare.write_text("{}")
    add_video(db, "a", metadata_path=str(counted))
    add_video(db, "b", metadata_path=str(bare))
    add_video(db, "c", metadata_path=str(tmp_path / "missing.json"))
    add_video(db, "d")
    db.commit()

    assert backfill_view_counts(db) == 2

    videos = {video.yt_video_id: video for video in db.scalars(select(Video))}
    # A readable file without a value gets 0 (not re-read); a missing file stays NULL (retried).
    assert {key: video.view_count for key, video in videos.items()} == {
        "a": 1234,
        "b": 0,
        "c": None,
        "d": None,
    }
    assert {key: video.duration_seconds for key, video in videos.items()} == {
        "a": 754,
        "b": 0,
        "c": None,
        "d": None,
    }


def test_uncategorized_filter_lists_videos_without_own_or_channel_labels(db):
    labeled_channel = Channel(
        name="Cuisine", url="https://youtube.com/@a", yt_channel_id="UCa", category_labels="cuisine"
    )
    bare_channel = Channel(name="Bare", url="https://youtube.com/@b", yt_channel_id="UCb")
    db.add_all([labeled_channel, bare_channel])
    db.flush()
    add_video(db, "own", bare_channel, category_labels="science")
    add_video(db, "inherited", labeled_channel)
    add_video(db, "empty", bare_channel, category_labels="")
    add_video(db, "orphan")
    db.commit()

    page = TestClient(app).get("/videos?asset_filters=1&uncategorized=1")

    assert page.status_code == 200
    titles = set(re.findall(r"Video (?:own|inherited|empty|orphan)", page.text))
    assert titles == {"Video empty", "Video orphan"}
    assert "Sans catégorie" in page.text
    # The active filter shows as a removable pill and counts as a category filter.
    assert 'href="/videos?asset_filters=1"' in page.text
