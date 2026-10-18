from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.video import TranscriptStatus, Video
from app.models.video_sponsor_segment import VideoSponsorSegment


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


def test_video_sponsor_segment_round_trip():
    db = make_session()
    video = add_video(db)

    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=42.0,
            end_seconds=105.5,
            source="sponsorblock",
        )
    )
    db.commit()

    row = db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
    assert row.category == "sponsor"
    assert row.start_seconds == 42.0
    assert row.end_seconds == 105.5
    assert row.source == "sponsorblock"
    assert row.created_at is not None


def test_video_sponsor_segment_cascades_on_video_delete():
    db = make_session()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id, category="sponsor", start_seconds=1.0, end_seconds=2.0, source="llm"
        )
    )
    db.commit()

    db.delete(video)
    db.commit()

    assert (
        db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
        is None
    )
