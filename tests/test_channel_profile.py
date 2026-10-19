import json
from datetime import UTC, datetime

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.setting import AppSetting
from app.services import background_jobs
from app.services import scheduler as scheduler_module
from app.services.channels import profile as channel_profile
from app.services.youtube import yt


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_channel_profile_columns_default_to_empty():
    db = make_session()
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()

    assert channel.description is None
    assert channel.avatar_path is None
    assert channel.banner_path is None
    assert channel.metadata_fetched_at is None
    assert channel.keyword_list == []


def test_keyword_list_reads_the_json_column_and_ignores_garbage():
    channel = Channel(url="u", name="n", keywords=json.dumps(["firebase", "web"]))
    assert channel.keyword_list == ["firebase", "web"]
    assert Channel(url="u", name="n", keywords="not json").keyword_list == []
    assert Channel(url="u", name="n", keywords=json.dumps({"a": 1})).keyword_list == []


class FakeYoutubeDL:
    info: dict = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return self.info


PROFILE_INFO = {
    "description": "  High-intensity code tutorials.  ",
    "tags": ["angular", " firebase ", "", 3],
    "thumbnails": [
        {"id": "0", "url": "https://img.test/small.jpg"},
        {"id": "banner_uncropped", "url": "//img.test/banner.jpg"},
        {"id": "avatar_uncropped", "url": "https://img.test/avatar.jpg"},
    ],
}


def test_fetch_channel_profile_picks_uncropped_images_and_cleans_text(monkeypatch):
    FakeYoutubeDL.info = PROFILE_INFO
    monkeypatch.setattr(yt, "YoutubeDL", FakeYoutubeDL)

    profile = yt.fetch_channel_profile("https://www.youtube.com/@x")

    assert profile == {
        "description": "High-intensity code tutorials.",
        "keywords": ["angular", "firebase"],
        "avatar_url": "https://img.test/avatar.jpg",
        "banner_url": "https://img.test/banner.jpg",
    }


def test_fetch_channel_profile_tolerates_missing_fields(monkeypatch):
    FakeYoutubeDL.info = {"thumbnails": None}
    monkeypatch.setattr(yt, "YoutubeDL", FakeYoutubeDL)

    assert yt.fetch_channel_profile("https://www.youtube.com/@x") == {
        "description": None,
        "keywords": [],
        "avatar_url": None,
        "banner_url": None,
    }


def make_session_with_media_root(tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.commit()
    return db


def fake_profile(**overrides):
    profile = {
        "description": "Une chaîne",
        "keywords": ["a", "b"],
        "avatar_url": "https://img.test/avatar.jpg",
        "banner_url": "https://img.test/banner.png",
    }
    return {**profile, **overrides}


def test_refresh_channel_profile_stores_text_and_images(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()
    monkeypatch.setattr(channel_profile.yt, "fetch_channel_profile", lambda url: fake_profile())
    monkeypatch.setattr(
        channel_profile,
        "fetch_image_bytes",
        lambda url: (
            (b"png-bytes", "image/png") if url.endswith(".png") else (b"jpg-bytes", "image/jpeg")
        ),
    )

    assert channel_profile.refresh_channel_profile(db, channel) is True

    assert channel.description == "Une chaîne"
    assert channel.keyword_list == ["a", "b"]
    assert channel.avatar_path == "_channels/UC1/avatar.jpg"
    assert channel.banner_path == "_channels/UC1/banner.png"
    assert (tmp_path / "_channels" / "UC1" / "avatar.jpg").read_bytes() == b"jpg-bytes"
    assert (tmp_path / "_channels" / "UC1" / "banner.png").read_bytes() == b"png-bytes"
    assert channel.metadata_fetched_at is not None


def test_refresh_keeps_the_rest_when_one_image_fails(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()
    monkeypatch.setattr(channel_profile.yt, "fetch_channel_profile", lambda url: fake_profile())

    def flaky(url):
        if url.endswith(".png"):
            raise OSError("boom")
        return b"jpg-bytes", "image/jpeg"

    monkeypatch.setattr(channel_profile, "fetch_image_bytes", flaky)

    assert channel_profile.refresh_channel_profile(db, channel) is True

    assert channel.avatar_path == "_channels/UC1/avatar.jpg"
    assert channel.banner_path is None
    assert channel.description == "Une chaîne"
    assert channel.metadata_fetched_at is not None


def test_refresh_leaves_the_channel_pending_when_yt_dlp_fails(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()

    def fail(url):
        raise RuntimeError("offline")

    monkeypatch.setattr(channel_profile.yt, "fetch_channel_profile", fail)

    assert channel_profile.refresh_channel_profile(db, channel) is False
    assert channel.metadata_fetched_at is None
    assert channel_profile.pending_profile_channel_ids(db) == [channel.id]


def test_refresh_replaces_an_image_whose_extension_changed(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()
    stale = tmp_path / "_channels" / "UC1" / "avatar.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    monkeypatch.setattr(
        channel_profile.yt, "fetch_channel_profile", lambda url: fake_profile(banner_url=None)
    )
    monkeypatch.setattr(channel_profile, "fetch_image_bytes", lambda url: (b"new", "image/jpeg"))

    channel_profile.refresh_channel_profile(db, channel)

    assert not stale.exists()
    assert (tmp_path / "_channels" / "UC1" / "avatar.jpg").read_bytes() == b"new"


def test_pending_profile_channels_skip_fetched_and_idless_channels(tmp_path):
    db = make_session_with_media_root(tmp_path)
    pending = Channel(url="u1", name="pending", yt_channel_id="UC1")
    done = Channel(
        url="u2", name="done", yt_channel_id="UC2", metadata_fetched_at=datetime.now(UTC)
    )
    idless = Channel(url="u3", name="idless", yt_channel_id=None)
    db.add_all([pending, done, idless])
    db.commit()

    assert channel_profile.pending_profile_channel_ids(db) == [pending.id]


def test_remove_channel_profile_files_only_touches_the_channels_folder(tmp_path):
    folder = tmp_path / "_channels" / "UC1"
    folder.mkdir(parents=True)
    (folder / "avatar.jpg").write_bytes(b"x")
    other = tmp_path / "Une chaine"
    other.mkdir()

    channel_profile.remove_channel_profile_files(tmp_path, "UC1")
    channel_profile.remove_channel_profile_files(tmp_path, "../Une chaine")
    channel_profile.remove_channel_profile_files(tmp_path, None)

    assert not folder.exists()
    assert other.exists()


def test_backfill_job_refreshes_each_pending_channel_with_a_pause(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    first = Channel(url="u1", name="un", yt_channel_id="UC1")
    second = Channel(url="u2", name="deux", yt_channel_id="UC2")
    done = Channel(
        url="u3", name="trois", yt_channel_id="UC3", metadata_fetched_at=datetime.now(UTC)
    )
    db.add_all([first, second, done])
    db.commit()
    refreshed, pauses = [], []
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        background_jobs,
        "refresh_channel_profile",
        lambda session, channel: refreshed.append(channel.id),
    )
    monkeypatch.setattr(background_jobs.time, "sleep", lambda seconds: pauses.append(seconds))

    background_jobs.run_channel_profile_backfill_job()

    assert refreshed == [first.id, second.id]
    assert pauses == [background_jobs.PROFILE_FETCH_DELAY_SECONDS]


def test_backfill_returns_at_once_when_another_sweep_is_running(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    db.add(Channel(url="u1", name="un", yt_channel_id="UC1"))
    db.commit()
    refreshed = []
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        background_jobs,
        "refresh_channel_profile",
        lambda session, channel: refreshed.append(channel.id),
    )

    with background_jobs._profile_backfill_lock:
        background_jobs.run_channel_profile_backfill_job()

    assert refreshed == []
    assert not background_jobs._profile_backfill_lock.locked()


def test_backfill_picks_up_a_channel_added_during_the_sweep(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    first = Channel(url="u1", name="un", yt_channel_id="UC1")
    db.add(first)
    db.commit()
    refreshed = []

    def refresh(session, channel):
        refreshed.append(channel.yt_channel_id)
        if channel.yt_channel_id == "UC1":
            session.add(Channel(url="u2", name="deux", yt_channel_id="UC2"))
        channel.metadata_fetched_at = datetime.now(UTC)
        session.commit()
        return True

    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(background_jobs, "refresh_channel_profile", refresh)
    monkeypatch.setattr(background_jobs.time, "sleep", lambda seconds: None)

    background_jobs.run_channel_profile_backfill_job()

    assert refreshed == ["UC1", "UC2"]


def test_backfill_attempts_a_failing_channel_once_per_run(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    db.add(Channel(url="u1", name="un", yt_channel_id="UC1"))
    db.commit()
    attempts = []
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        background_jobs,
        "refresh_channel_profile",
        lambda session, c: attempts.append(c.id) or False,
    )
    monkeypatch.setattr(background_jobs.time, "sleep", lambda seconds: None)

    background_jobs.run_channel_profile_backfill_job()

    assert len(attempts) == 1


def test_backfill_continues_after_one_channel_raises(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    db.add_all(
        [
            Channel(url="u1", name="un", yt_channel_id="UC1"),
            Channel(url="u2", name="deux", yt_channel_id="UC2"),
        ]
    )
    db.commit()
    refreshed = []

    def refresh(session, channel):
        if channel.yt_channel_id == "UC1":
            raise RuntimeError("stale data")
        refreshed.append(channel.yt_channel_id)

    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(background_jobs, "refresh_channel_profile", refresh)
    monkeypatch.setattr(background_jobs.time, "sleep", lambda seconds: None)

    background_jobs.run_channel_profile_backfill_job()

    assert refreshed == ["UC2"]


def test_store_image_leaves_no_part_file_when_the_replace_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(channel_profile, "fetch_image_bytes", lambda url: (b"x", "image/png"))

    def broken_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(channel_profile.os, "replace", broken_replace)

    try:
        channel_profile.store_image("https://img.test/a.png", tmp_path / "UC1" / "avatar")
    except OSError:
        pass

    assert list((tmp_path / "UC1").iterdir()) == []


def test_refresh_job_refreshes_the_given_channel_even_if_already_fetched(monkeypatch, tmp_path):
    db = make_session_with_media_root(tmp_path)
    channel = Channel(
        url="u1", name="un", yt_channel_id="UC1", metadata_fetched_at=datetime.now(UTC)
    )
    db.add(channel)
    db.commit()
    refreshed = []
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        background_jobs, "refresh_channel_profile", lambda session, c: refreshed.append(c.id)
    )

    background_jobs.run_channel_profile_refresh_job(channel.id)
    background_jobs.run_channel_profile_refresh_job(9999)

    assert refreshed == [channel.id]


def test_start_scheduler_queues_a_profile_backfill_at_startup(monkeypatch, tmp_path):
    class FakeScheduler:
        running = False

        def __init__(self):
            self.job_ids = []

        def add_job(self, func, *args, **kwargs):
            self.job_ids.append(kwargs.get("id"))

        def start(self):
            pass

    fake = FakeScheduler()
    db = make_session_with_media_root(tmp_path)
    monkeypatch.setattr(scheduler_module, "scheduler", fake)
    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db)

    scheduler_module.start_scheduler()

    assert scheduler_module.PROFILE_BACKFILL_JOB_ID in fake.job_ids


def test_toolbox_remembers_channels_it_added():
    from app.services.rag.library_chat_tools import LibraryChatToolbox

    db = make_session()
    toolbox = LibraryChatToolbox(db)
    toolbox.youtube_candidates = {
        "UCleo": {
            "url": "https://www.youtube.com/@leo",
            "name": "Léo",
            "handle": "@leo",
            "subscriber_count": None,
        }
    }

    toolbox.run("ajouter_chaine", {"youtube_id": "UCleo"})

    assert len(toolbox.added_channel_ids) == 1


def make_client(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    channel = Channel(url="https://example.test/c", name="C", yt_channel_id="UC1")
    db.add(channel)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db, channel


def test_avatar_and_banner_routes_serve_the_stored_files(tmp_path):
    client, db, channel = make_client(tmp_path)
    folder = tmp_path / "_channels" / "UC1"
    folder.mkdir(parents=True)
    (folder / "avatar.jpg").write_bytes(b"jpg-bytes")
    (folder / "banner.png").write_bytes(b"png-bytes")
    channel.avatar_path = "_channels/UC1/avatar.jpg"
    channel.banner_path = "_channels/UC1/banner.png"
    db.commit()
    try:
        avatar = client.get(f"/channels/{channel.id}/avatar")
        banner = client.get(f"/channels/{channel.id}/banner")
    finally:
        app.dependency_overrides.clear()

    assert avatar.status_code == 200 and avatar.content == b"jpg-bytes"
    assert banner.status_code == 200 and banner.content == b"png-bytes"
    assert avatar.headers["cache-control"] == "public, max-age=86400"


def test_images_are_written_and_served_through_the_dev_pc_prefix_translation(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    from app.core import config

    local = tmp_path / "local-mount"
    local.mkdir()
    # The media_root setting holds the server's path, which does not exist here.
    client, db, channel = make_client(Path("/server/media"))
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            media_root_remote_prefix=Path("/server/media"), media_root_local_prefix=local
        ),
    )
    monkeypatch.setattr(
        channel_profile.yt, "fetch_channel_profile", lambda url: fake_profile(banner_url=None)
    )
    monkeypatch.setattr(
        channel_profile, "fetch_image_bytes", lambda url: (b"jpg-bytes", "image/jpeg")
    )
    try:
        channel_profile.refresh_channel_profile(db, channel)
        response = client.get(f"/channels/{channel.id}/avatar")
    finally:
        app.dependency_overrides.clear()

    assert channel.avatar_path == "_channels/UC1/avatar.jpg"
    assert (local / "_channels" / "UC1" / "avatar.jpg").read_bytes() == b"jpg-bytes"
    assert response.status_code == 200 and response.content == b"jpg-bytes"
    channel_profile.remove_channel_profile_files(Path("/server/media"), "UC1")
    assert not (local / "_channels" / "UC1").exists()


def test_image_routes_404_when_missing_or_outside_the_channels_folder(tmp_path):
    client, db, channel = make_client(tmp_path)
    (tmp_path / "secret.txt").write_text("secret")
    try:
        assert client.get(f"/channels/{channel.id}/avatar").status_code == 404
        channel.avatar_path = "../secret.txt"
        channel.banner_path = "secret.txt"
        db.commit()
        assert client.get(f"/channels/{channel.id}/avatar").status_code == 404
        assert client.get(f"/channels/{channel.id}/banner").status_code == 404
        assert client.get("/channels/999/avatar").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_refresh_profile_route_queues_a_refresh_for_that_channel(tmp_path, monkeypatch):
    client, db, channel = make_client(tmp_path)
    queued = []
    monkeypatch.setattr(
        BackgroundTasks, "add_task", lambda self, func, *args: queued.append((func.__name__, args))
    )
    try:
        response = client.post(
            f"/channels/{channel.id}/refresh-profile",
            data={"next": "/channels"},
            follow_redirects=False,
        )
        missing = client.post(
            "/channels/999/refresh-profile", data={"next": "/channels"}, follow_redirects=False
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    assert queued == [("run_channel_profile_refresh_job", (channel.id,))]
    assert missing.status_code == 404


def test_deleting_a_channel_removes_its_profile_folder(tmp_path):
    client, db, channel = make_client(tmp_path)
    folder = tmp_path / "_channels" / "UC1"
    folder.mkdir(parents=True)
    (folder / "avatar.jpg").write_bytes(b"x")
    try:
        client.post(
            f"/channels/{channel.id}/delete", data={"next": "/channels"}, follow_redirects=False
        )
    finally:
        app.dependency_overrides.clear()

    assert not folder.exists()


def test_adding_a_channel_queues_the_profile_backfill(tmp_path, monkeypatch):
    from app.web.routes import channels as channels_routes

    client, db, channel = make_client(tmp_path)
    app.dependency_overrides.clear()
    monkeypatch.setattr(
        channels_routes,
        "extract_channel_info",
        lambda url: {"url": "https://example.test/new", "name": "Nouvelle", "yt_channel_id": "UC2"},
    )
    tasks = BackgroundTasks()

    channels_routes.add_channel("@nouvelle", db, background_tasks=tasks)

    assert [task.func.__name__ for task in tasks.tasks] == ["run_channel_profile_backfill_job"]


def give_profile(db, channel, description="High-intensity <b>tutorials</b>"):
    channel.description = description
    channel.keywords = json.dumps(["angular", "firebase"])
    channel.avatar_path = "_channels/UC1/avatar.jpg"
    channel.banner_path = "_channels/UC1/banner.jpg"
    channel.metadata_fetched_at = datetime(2026, 10, 9, tzinfo=UTC)
    db.commit()


def test_channels_list_shows_the_banner_and_avatar_but_not_the_profile_text(tmp_path):
    client, db, channel = make_client(tmp_path)
    give_profile(db, channel)
    try:
        html = client.get("/channels?rated=false").text
    finally:
        app.dependency_overrides.clear()

    assert f'src="/channels/{channel.id}/avatar?v=' in html
    assert f'src="/channels/{channel.id}/banner?v=' in html
    assert "High-intensity" not in html
    assert ">angular<" not in html
    assert "refresh-profile" not in html


def test_channel_page_shows_banner_avatar_description_keywords_and_refresh(tmp_path):
    client, db, channel = make_client(tmp_path)
    give_profile(db, channel)
    try:
        html = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()

    assert f'src="/channels/{channel.id}/avatar?v=' in html
    assert f'src="/channels/{channel.id}/banner?v=' in html
    assert "High-intensity &lt;b&gt;tutorials&lt;/b&gt;" in html
    assert ">angular<" in html and ">firebase<" in html
    assert f'action="/channels/{channel.id}/refresh-profile"' in html


def test_channel_page_falls_back_to_an_initial_and_omits_empty_profile_parts(tmp_path):
    client, db, channel = make_client(tmp_path)
    try:
        html = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()

    assert f"/channels/{channel.id}/avatar" not in html
    assert f"/channels/{channel.id}/banner" not in html
    assert "channel-avatar-initial" in html
    assert 'class="channel-description"' not in html
    assert 'aria-label="Mots-clés"' not in html


def test_channel_page_youtube_link_is_discreet_and_opens_in_a_new_tab(tmp_path):
    client, db, channel = make_client(tmp_path)
    try:
        html = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()

    assert 'class="channel-youtube-link"' in html
    assert 'href="https://example.test/c"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    # The full URL is no longer printed as the link text.
    assert ">https://example.test/c<" not in html


def test_channel_page_only_offers_to_expand_a_long_description(tmp_path):
    client, db, channel = make_client(tmp_path)
    try:
        give_profile(db, channel, description="Courte description")
        short = client.get(f"/videos?channel_id={channel.id}").text
        give_profile(db, channel, description="Très longue description. " * 20)
        long = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()

    assert "channel-description-more" not in short
    assert "channel-description-more" in long


def test_channels_page_falls_back_to_an_initial_without_avatar(tmp_path):
    client, db, channel = make_client(tmp_path)
    try:
        html = client.get("/channels?rated=false").text
    finally:
        app.dependency_overrides.clear()

    assert f"/channels/{channel.id}/avatar" not in html
    assert 'class="channel-avatar channel-card-avatar channel-avatar-initial"' in html
    assert f"/channels/{channel.id}/banner" not in html
    assert "channel-banner-fallback" in html
