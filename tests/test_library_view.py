"""`library_view`: what the library shows for a set of filters, called without HTTP."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.user import UserSetting
from back.models.video import Video
from back.services.videos.library_view import (
    LIBRARY_PAGE_SIZE,
    LibraryFilters,
    library_cards,
    library_listing,
    library_saved_views,
)
from tests.site import site_client
from tests.users import (
    CHANNEL_STATE_FIELDS,
    VIDEO_STATE_FIELDS,
    pop_state,
    set_channel_state,
    set_video_state,
    user_id,
)

NOW = datetime(2026, 10, 9, tzinfo=UTC)


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
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_channel(db, name, **fields):
    state = pop_state(fields, CHANNEL_STATE_FIELDS)
    channel = Channel(
        name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}", **fields
    )
    db.add(channel)
    db.flush()
    if state:
        set_channel_state(db, channel, **state)
    return channel


def add_video(db, key, channel, *, short=False, minutes=0, **fields):
    state = pop_state(fields, VIDEO_STATE_FIELDS)
    video = Video(
        channel_id=channel.id,
        yt_video_id=key,
        title=key,
        url=f"https://youtube.com/{'shorts/' if short else 'watch?v='}{key}",
        folder_path=f"/media/{key}",
        video_path=f"/media/{key}/v.mp4",
        downloaded_at=NOW + timedelta(minutes=minutes),
        published_at=NOW - timedelta(days=minutes),
        **fields,
    )
    db.add(video)
    db.flush()
    if state:
        set_video_state(db, video, **state)
    return video


def test_library_listing_pages_the_whole_library_newest_first(db):
    channel = add_channel(db, "Chan")
    for index in range(LIBRARY_PAGE_SIZE + 3):
        add_video(db, f"v{index}", channel, minutes=index)
    db.commit()

    first = library_listing(db, user_id(db), LibraryFilters(assets=frozenset({"video"})))
    last = library_listing(db, user_id(db), LibraryFilters(assets=frozenset({"video"}), page=99))

    assert first.channel is None
    assert first.section == "videos"
    assert first.publication_dates is None
    assert (first.page, first.total_pages, first.filtered_video_count) == (1, 2, 53)
    assert first.videos[0].title == f"v{LIBRARY_PAGE_SIZE + 2}"
    assert last.page == 2
    assert [video.title for video in last.videos] == ["v2", "v1", "v0"]


def test_library_listing_opens_a_shorts_only_channel_on_its_shorts(db):
    channel = add_channel(db, "Shorts", auto_shorts_enabled=True, auto_metadata_enabled=False)
    add_video(db, "long", channel)
    add_video(db, "short", channel, short=True)
    db.commit()
    every_asset = frozenset({"video", "shorts", "metadata", "transcript", "audio", "imported"})

    default = library_listing(
        db, user_id(db), LibraryFilters(channel_id=channel.id, assets=every_asset)
    )
    videos = library_listing(
        db, user_id(db), LibraryFilters(channel_id=channel.id, section="videos", assets=every_asset)
    )

    assert default.channel == channel
    assert default.section == "shorts"
    assert [video.title for video in default.videos] == ["short"]
    assert [video.title for video in videos.videos] == ["long"]
    assert default.publication_dates is not None


def test_library_cards_carry_the_latest_playback(db):
    video = add_video(db, "v", add_channel(db, "Chan"), duration_seconds=125)
    db.commit()

    [card] = library_cards(db, user_id(db), [video])

    assert card["video"] is video
    assert card["channel_name"] == "Chan"
    assert card["duration"] == "2:05"
    assert card["playback"] is None


def test_library_saved_views_flag_the_one_matching_the_filters(db):
    db.add(
        UserSetting(
            user_id=user_id(db),
            key="video_library_views",
            value='[{"name":"Notés","rated":true},{"name":"Audio","assets":["audio"]}]',
        )
    )
    db.commit()

    views = library_saved_views(db, user_id(db), LibraryFilters(rated_only=True))

    assert [(view["name"], view["active"]) for view in views] == [
        ("Notés", True),
        ("Audio", False),
    ]


def test_videos_page_reads_its_filters_from_the_query_string(db):
    channel = add_channel(db, "Chan")
    add_video(db, "kept", channel, rating=4)
    add_video(db, "unrated", channel, minutes=1)
    db.commit()

    page = site_client().get("/videos?asset_filters=1&asset=video&rated=1")

    assert page.status_code == 200
    assert ">kept<" in page.text
    assert ">unrated<" not in page.text
