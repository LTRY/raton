"""`GET /api/library`: the library list as JSON, same filters as `/videos`."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.user import UserSetting
from back.models.video import Video
from back.services.common.library_views import VIDEO_ASSET_KINDS
from front.library import VIDEO_ASSET_FILTER_OPTIONS
from tests.users import VIDEO_STATE_FIELDS, pop_state, set_video_state, user_id

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
    session.statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: session.statements.append(args[2]))
    # Created up front, so the first request does not count its INSERT.
    user_id(session)
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_channel(db, name):
    channel = Channel(name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}")
    db.add(channel)
    db.flush()
    return channel


def add_video(db, key, channel, *, minutes=0, short=False, **fields):
    state = pop_state(fields, VIDEO_STATE_FIELDS)
    video = Video(
        channel_id=channel.id,
        yt_video_id=key,
        title=key,
        url=f"https://youtube.com/{'shorts/' if short else 'watch?v='}{key}",
        folder_path=f"/media/{key}",
        downloaded_at=NOW + timedelta(minutes=minutes),
        published_at=NOW - timedelta(days=minutes),
        **fields,
    )
    db.add(video)
    db.flush()
    if state:
        set_video_state(db, video, **state)
    return video


def test_api_library_lists_cards_with_their_playback_and_applied_filters(db):
    channel = add_channel(db, "Chan")
    played = add_video(
        db, "played", channel, minutes=1, audio_path="/media/played/a.m4a", duration_seconds=100
    )
    add_video(db, "other", channel, video_path="/media/other/v.mp4", is_new=True)
    db.add(
        DownloadJob(
            status="played",
            video_id=played.id,
            user_id=user_id(db),
            message=json.dumps(
                {"type": "playback", "position_seconds": 50, "duration_seconds": 100}
            ),
        )
    )
    db.commit()

    payload = TestClient(app).get("/api/library").json()

    assert (payload["page"], payload["total_pages"], payload["total"]) == (1, 1, 2)
    assert payload["channel"] is None
    assert payload["section"] == "videos"
    assert payload["filters"]["sort"] == "imported"
    assert payload["filters"]["assets"] == []
    first, second = payload["items"]
    assert first["title"] == "played"
    assert first["channel_name"] == "Chan"
    assert (first["has_audio"], first["has_video"]) == (True, False)
    assert first["playback"] == {
        "position_seconds": 50.0,
        "duration_seconds": 100.0,
        "progress_percent": 50.0,
        "is_completed": False,
    }
    assert second["is_new"] is True
    assert second["playback"] is None
    assert set(payload["counts"]) >= {"local_video_count", "downloaded_video_count"}


def test_api_library_normalizes_filters_like_the_videos_page(db):
    channel = add_channel(db, "Chan")
    add_video(db, "audio", channel, audio_path="/media/audio/a.m4a", category_labels="cuisine")
    add_video(db, "video", channel, video_path="/media/video/v.mp4", minutes=1)
    db.commit()

    payload = (
        TestClient(app)
        .get(
            "/api/library?asset=audio&asset=nope&category=%20Cuisine%20&sort=bogus"
            "&asset_filter_mode=bogus&q=%20%20audio%20"
        )
        .json()
    )

    assert payload["filters"]["assets"] == ["audio"]
    assert payload["filters"]["categories"] == ["cuisine"]
    assert payload["filters"]["sort"] == "imported"
    assert payload["filters"]["asset_filter_mode"] == "or"
    assert payload["filters"]["q"] == "audio"
    assert [item["title"] for item in payload["items"]] == ["audio"]


def test_api_library_opens_a_channel_on_its_section(db):
    channel = add_channel(db, "Chan")
    add_video(db, "long", channel)
    add_video(db, "short", channel, short=True)
    db.commit()
    client = TestClient(app)

    videos = client.get(f"/api/library?channel_id={channel.id}").json()
    shorts = client.get(f"/api/library?channel_id={channel.id}&section=shorts").json()

    assert videos["channel"] == {"id": channel.id, "name": "Chan"}
    assert videos["filters"]["sort"] == "published"
    assert [item["title"] for item in videos["items"]] == ["long"]
    assert [item["title"] for item in shorts["items"]] == ["short"]


def test_api_library_refuses_an_unknown_channel(db):
    response = TestClient(app).get("/api/library?channel_id=999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Chaîne introuvable"}


def test_api_library_flags_the_active_saved_view(db):
    db.add(
        UserSetting(
            user_id=user_id(db),
            key="video_library_views",
            value='[{"name":"Notés","rated":true},{"name":"Audio","assets":["audio"]}]',
        )
    )
    db.commit()

    payload = TestClient(app).get("/api/library?rated=true").json()

    assert [(view["name"], view["active"]) for view in payload["saved_views"]] == [
        ("Notés", True),
        ("Audio", False),
    ]


def test_api_library_statement_count_does_not_grow_with_the_library(db):
    channel = add_channel(db, "Chan")
    for index in range(3):
        add_video(db, f"a{index}", channel, minutes=index, video_path="/media/v.mp4")
    db.commit()
    client = TestClient(app)
    db.statements.clear()
    client.get("/api/library")
    small = len(db.statements)

    for index in range(60):
        add_video(db, f"b{index}", channel, minutes=10 + index, video_path="/media/v.mp4")
    db.commit()
    db.statements.clear()
    client.get("/api/library")

    assert len(db.statements) == small


def test_the_videos_page_offers_every_valid_file_type():
    assert {option["kind"] for option in VIDEO_ASSET_FILTER_OPTIONS} == VIDEO_ASSET_KINDS
