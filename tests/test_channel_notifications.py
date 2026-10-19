from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.session import Base
from app.models.channel import Channel
from app.models.video import TranscriptStatus, Video
from app.services.channels import scanner
from app.web.routes import channels as channels_routes
from app.web.routes import videos as videos_routes


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_daily_scan_only_processes_channels_with_the_bell_enabled(monkeypatch):
    db = make_session()
    enabled = Channel(url="https://example.test/enabled", name="Suivie", auto_metadata_enabled=True)
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
        (enabled.id, {"mark_new": True, "max_imports": scanner.MAX_IMPORTS_PER_SECTION})
    ]


def test_daily_scan_scans_only_the_sections_whose_bell_is_on(monkeypatch):
    db = make_session()
    both = Channel(
        url="https://example.test/both",
        name="Tout",
        auto_metadata_enabled=True,
        auto_shorts_enabled=True,
    )
    shorts_only = Channel(
        url="https://example.test/shorts", name="Shorts", auto_shorts_enabled=True
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
            scanned.append((channel.id, kwargs["section"], kwargs["mark_new"])) or 1
        ),
    )

    result = scanner.run_scan(db)

    assert result["downloaded"] == 3
    assert sorted(scanned, key=lambda item: (item[0], item[1])) == [
        (both.id, "shorts", True),
        (both.id, "videos"),
        (shorts_only.id, "shorts", True),
    ]


def test_enabling_the_bell_starts_a_new_metadata_import():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne suivie")
    db.add(channel)
    db.commit()
    tasks = BackgroundTasks()

    response = channels_routes.toggle_channel_auto_metadata_form(
        tasks, channel.id, "/channels", db, "videos"
    )

    assert channel.auto_metadata_enabled is True
    assert channel.auto_shorts_enabled is False
    assert response.status_code == 303
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].args[-2:] == ("videos", False)


def test_the_shorts_bell_toggles_independently_and_imports_the_shorts_section():
    db = make_session()
    channel = Channel(
        url="https://example.test/channel", name="Chaîne suivie", auto_metadata_enabled=True
    )
    db.add(channel)
    db.commit()
    tasks = BackgroundTasks()

    channels_routes.toggle_channel_auto_metadata_form(tasks, channel.id, "/channels", db, "shorts")

    assert channel.auto_shorts_enabled is True
    assert channel.auto_metadata_enabled is True
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].args[-2:] == ("shorts", False)

    channels_routes.toggle_channel_auto_metadata_form(tasks, channel.id, "/channels", db, "shorts")

    assert channel.auto_shorts_enabled is False
    assert channel.auto_metadata_enabled is True
    assert len(tasks.tasks) == 1


def test_visiting_a_new_video_clears_its_new_label():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne")
    video = Video(
        channel=channel,
        yt_video_id="new123",
        title="Nouvelle fiche",
        url="https://youtube.com/watch?v=new123",
        folder_path="/media/video",
        transcript_status=TranscriptStatus.missing,
        is_new=True,
    )
    db.add(video)
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos/1",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    videos_routes.video_detail_page(request, video.id, db)

    assert video.is_new is False
