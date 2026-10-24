import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.video import TranscriptStatus, Video
from back.services.ingest import scanner
from tests.users import (
    FIRST_USER_ID,
    add_user,
    follow,
    mine,
    my_channel,
    stored_channel_state,
    stored_video_state,
)


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture
def imports(monkeypatch):
    """The catalogue imports a cloche turned on queues, recorded instead of run."""
    started = []
    monkeypatch.setattr(
        "back.api.channels.run_channel_metadata_import_job", lambda *args: started.append(args)
    )
    return started


def test_daily_scan_only_processes_channels_with_the_bell_enabled(monkeypatch):
    db = make_session()
    enabled = Channel(
        url="https://example.test/enabled",
        name="Suivie",
        user_states=my_channel(auto_metadata_enabled=True),
    )
    disabled = Channel(url="https://example.test/disabled", name="Silencieuse")
    db.add_all([enabled, disabled])
    db.commit()
    scanned = []
    monkeypatch.setattr(
        scanner,
        "scan_channel",
        lambda db, channel, **kwargs: scanned.append((channel.id, kwargs)) or 2,
    )

    result = scanner.run_scan(db)

    assert result["status"] == "completed"
    assert result["downloaded"] == 2
    assert scanned == [
        (enabled.id, {"new_for": [FIRST_USER_ID], "max_imports": scanner.MAX_IMPORTS_PER_SECTION})
    ]


def test_daily_scan_makes_each_section_news_for_its_followers_only(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/both", name="Deux publics")
    db.add(channel)
    db.commit()
    videos_fan = add_user(db, "Vidéos")
    shorts_fan = add_user(db, "Shorts")
    follow(db, channel, user=videos_fan.id)
    follow(db, channel, videos=False, shorts=True, user=shorts_fan.id)
    scanned = []
    monkeypatch.setattr(
        scanner,
        "scan_channel",
        lambda db, channel, **kwargs: scanned.append(("videos", kwargs["new_for"])) or 0,
    )
    monkeypatch.setattr(
        scanner,
        "scan_channel_section",
        lambda db, channel, **kwargs: scanned.append((kwargs["section"], kwargs["new_for"])) or 0,
    )

    scanner.run_scan(db)

    # The default user follows nothing here: nothing is news for them.
    assert scanned == [("videos", [videos_fan.id]), ("shorts", [shorts_fan.id])]


def test_daily_scan_scans_only_the_sections_whose_bell_is_on(monkeypatch):
    db = make_session()
    both = Channel(
        url="https://example.test/both",
        name="Tout",
        user_states=my_channel(auto_metadata_enabled=True, auto_shorts_enabled=True),
    )
    shorts_only = Channel(
        url="https://example.test/shorts",
        name="Shorts",
        user_states=my_channel(auto_shorts_enabled=True),
    )
    db.add_all([both, shorts_only])
    db.commit()
    scanned = []
    monkeypatch.setattr(
        scanner,
        "scan_channel",
        lambda db, channel, **kwargs: scanned.append((channel.id, "videos")) or 1,
    )
    monkeypatch.setattr(
        scanner,
        "scan_channel_section",
        lambda db, channel, **kwargs: (
            scanned.append((channel.id, kwargs["section"], kwargs["new_for"])) or 1
        ),
    )

    result = scanner.run_scan(db)

    assert result["downloaded"] == 3
    assert sorted(scanned, key=lambda item: (item[0], item[1])) == [
        (both.id, "shorts", [FIRST_USER_ID]),
        (both.id, "videos"),
        (shorts_only.id, "shorts", [FIRST_USER_ID]),
    ]


def test_enabling_the_bell_starts_a_new_metadata_import(front_client, imports):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne suivie")
    db.add(channel)
    db.commit()

    response = front_client(db).post(
        f"/channels/{channel.id}/auto-metadata",
        data={"next": "/channels", "section": "videos"},
        follow_redirects=False,
    )

    state = stored_channel_state(db, channel)
    assert state.auto_metadata_enabled is True
    assert state.auto_shorts_enabled is False
    assert response.status_code == 303
    assert len(imports) == 1
    assert imports[0][-1] == "videos"


def test_the_shorts_bell_toggles_independently_and_imports_the_shorts_section(
    front_client, imports
):
    db = make_session()
    channel = Channel(
        url="https://example.test/channel",
        name="Chaîne suivie",
        user_states=my_channel(auto_metadata_enabled=True),
    )
    db.add(channel)
    db.commit()
    client = front_client(db)
    toggle = {"next": "/channels", "section": "shorts"}

    client.post(f"/channels/{channel.id}/auto-metadata", data=toggle, follow_redirects=False)

    state = stored_channel_state(db, channel)
    assert state.auto_shorts_enabled is True
    assert state.auto_metadata_enabled is True
    assert len(imports) == 1
    assert imports[0][-1] == "shorts"

    client.post(f"/channels/{channel.id}/auto-metadata", data=toggle, follow_redirects=False)

    state = stored_channel_state(db, channel)
    assert state.auto_shorts_enabled is False
    assert state.auto_metadata_enabled is True
    assert len(imports) == 1


def test_visiting_a_new_video_clears_its_new_label(front_client):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    video = Video(
        channel=channel,
        yt_video_id="new123",
        title="Nouvelle fiche",
        url="https://youtube.com/watch?v=new123",
        folder_path="/media/video",
        transcript_status=TranscriptStatus.missing,
        user_states=mine(is_new=True),
    )
    db.add(video)
    db.commit()

    front_client(db).get(f"/videos/{video.id}")

    assert stored_video_state(db, video).is_new is False
