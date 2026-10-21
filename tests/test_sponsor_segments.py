from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.video import TranscriptStatus, Video
from back.models.video_sponsor_segment import VideoSponsorSegment
from back.services.youtube.sponsor_segments import (
    MINIMUM_SKIP_SECONDS,
    normalize_skip_segments,
    replace_video_sponsor_segments,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(db):
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    video = Video(
        channel=channel,
        yt_video_id="abc123",
        title="Vidéo test",
        url="https://youtube.com/watch?v=abc123",
        media_type="video",
        folder_path="/media/video",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()
    return video


def test_replace_video_sponsor_segments_inserts_rows():
    db = make_session()
    video = add_video(db)

    rows = replace_video_sponsor_segments(
        db,
        video.id,
        "sponsorblock",
        [{"category": "sponsor", "start_seconds": 1.0, "end_seconds": 2.0}],
    )

    assert len(rows) == 1
    assert rows[0].id is not None
    stored = list(
        db.scalars(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
    )
    assert len(stored) == 1


def test_replace_video_sponsor_segments_replaces_only_same_source():
    db = make_session()
    video = add_video(db)
    replace_video_sponsor_segments(
        db,
        video.id,
        "sponsorblock",
        [{"category": "sponsor", "start_seconds": 1.0, "end_seconds": 2.0}],
    )
    replace_video_sponsor_segments(
        db, video.id, "llm", [{"category": "intro", "start_seconds": 0.0, "end_seconds": 5.0}]
    )

    replace_video_sponsor_segments(
        db,
        video.id,
        "sponsorblock",
        [{"category": "outro", "start_seconds": 500.0, "end_seconds": 520.0}],
    )

    stored = list(
        db.scalars(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
    )
    by_source = {(row.source, row.category) for row in stored}
    assert by_source == {("llm", "intro"), ("sponsorblock", "outro")}


def test_replace_video_sponsor_segments_with_empty_list_clears_source():
    db = make_session()
    video = add_video(db)
    replace_video_sponsor_segments(
        db,
        video.id,
        "sponsorblock",
        [{"category": "sponsor", "start_seconds": 1.0, "end_seconds": 2.0}],
    )

    result = replace_video_sponsor_segments(db, video.id, "sponsorblock", [])

    assert result == []
    assert (
        db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
        is None
    )


def test_normalize_skip_segments_returns_empty_list_for_no_rows():
    assert normalize_skip_segments([]) == []


def test_normalize_skip_segments_sorts_by_start():
    rows = [
        SimpleNamespace(start_seconds=100.0, end_seconds=130.0),
        SimpleNamespace(start_seconds=10.0, end_seconds=40.0),
    ]

    assert normalize_skip_segments(rows) == [
        {"start": 10.0, "end": 40.0},
        {"start": 100.0, "end": 130.0},
    ]


def test_normalize_skip_segments_merges_overlapping_segments():
    rows = [
        SimpleNamespace(start_seconds=10.0, end_seconds=40.0),
        SimpleNamespace(start_seconds=30.0, end_seconds=55.0),
    ]

    assert normalize_skip_segments(rows) == [{"start": 10.0, "end": 55.0}]


def test_normalize_skip_segments_merges_adjacent_segments():
    rows = [
        SimpleNamespace(start_seconds=10.0, end_seconds=40.0),
        SimpleNamespace(start_seconds=40.0, end_seconds=60.0),
    ]

    assert normalize_skip_segments(rows) == [{"start": 10.0, "end": 60.0}]


def test_normalize_skip_segments_merges_fully_contained_segment():
    rows = [
        SimpleNamespace(start_seconds=10.0, end_seconds=90.0),
        SimpleNamespace(start_seconds=20.0, end_seconds=30.0),
    ]

    assert normalize_skip_segments(rows) == [{"start": 10.0, "end": 90.0}]


def test_normalize_skip_segments_drops_segments_shorter_than_one_second():
    rows = [
        SimpleNamespace(start_seconds=10.0, end_seconds=10.4),
        SimpleNamespace(start_seconds=50.0, end_seconds=80.0),
    ]

    assert normalize_skip_segments(rows) == [{"start": 50.0, "end": 80.0}]


def test_normalize_skip_segments_keeps_segment_exactly_at_the_minimum_duration():
    # Borne exacte : MINIMUM_SKIP_SECONDS est une durée minimale incluse (10.0 →
    # 11.0 est conservé). Passer la comparaison de `>=` à `>` casse ce test.
    end = 10.0 + MINIMUM_SKIP_SECONDS
    rows = [SimpleNamespace(start_seconds=10.0, end_seconds=end)]

    assert normalize_skip_segments(rows) == [{"start": 10.0, "end": end}]


def test_normalize_skip_segments_keeps_short_segments_that_become_long_after_merge():
    rows = [
        SimpleNamespace(start_seconds=10.0, end_seconds=10.4),
        SimpleNamespace(start_seconds=10.2, end_seconds=12.0),
    ]

    assert normalize_skip_segments(rows) == [{"start": 10.0, "end": 12.0}]
