from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.video import Video
from back.services.videos.filters import video_asset_kind_condition
from back.services.videos.playback import latest_playback_by_video
from scripts.demo_seed import DEMO_VIDEOS, seed_demo


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_seed_demo_fills_an_empty_database():
    db = make_session()

    assert seed_demo(db) is True

    assert db.scalar(select(func.count(Channel.id))) == 3
    assert db.scalar(select(func.count(Video.id))) == len(DEMO_VIDEOS)


def test_seed_demo_is_idempotent():
    db = make_session()
    seed_demo(db)

    assert seed_demo(db) is False

    assert db.scalar(select(func.count(Video.id))) == len(DEMO_VIDEOS)


def test_seed_demo_gives_cards_a_progress_bar():
    # The demo shows every shape of card, the progress bar on the thumbnail included.
    db = make_session()
    seed_demo(db)

    videos = db.scalars(select(Video)).all()
    played = latest_playback_by_video(db, [video.id for video in videos])
    assert len(played) == sum(1 for _, _, _, share, _ in DEMO_VIDEOS if share is not None)
    assert all(video.list_state is None for video in videos if video.id in played)


def test_seed_demo_fills_exploration_default_filter():
    # Exploration keeps fiches holding a video or an audio file by default: the demo must show some.
    db = make_session()
    seed_demo(db)

    shown = db.scalar(
        select(func.count(Video.id)).where(
            or_(video_asset_kind_condition("video"), video_asset_kind_condition("audio"))
        )
    )
    assert 0 < shown < len(DEMO_VIDEOS)
