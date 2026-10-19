import io
from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.job import DownloadJob
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.common.job_log import log_job
from app.services.ingest.throttle import RateLimitedError
from app.services.playlists import imports as playlists_service
from app.services.playlists.editing import playlist_title_from_filename
from app.services.playlists.imports import (
    PlaylistCsvError,
    PlaylistNotFoundError,
    parse_playlist_csv,
    run_playlist_csv_import_job,
)
from app.web.routes import playlists as playlists_routes

CSV_SAMPLE = (
    "ID vidéo,Code temporel de création de la vidéo de la playlist\n"
    "yLVcRkFtEcA,2026-01-19T11:10:42+00:00\n"
    "IOvqN23Sr4o,2026-01-19T11:10:48+00:00\n"
).encode("utf-8-sig")


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_request(method="POST", path="/playlists", headers=None):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": headers or [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def add_video(db, yt_video_id="v1", title="V1"):
    video = Video(
        yt_video_id=yt_video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={yt_video_id}",
        folder_path=f"/media/{yt_video_id}",
        media_type="metadata",
    )
    db.add(video)
    db.commit()
    return video


def fake_import_video_metadata(
    db,
    video_url,
    channel_id=None,
    preview=None,
    download_source="manual",
    source_section="videos",
    subtitle_languages=None,
    subtitle_source="auto",
    is_new=False,
):
    """Stands in for app.services.ingest.scanner.import_video_metadata in tests:
    same get-or-create-by-yt_video_id idempotency, no yt-dlp/network calls.
    """
    yt_video_id = (preview or {}).get("id") or video_url.rsplit("v=", 1)[-1]
    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    if existing:
        return existing
    video = Video(
        yt_video_id=yt_video_id,
        title=(preview or {}).get("title") or yt_video_id,
        url=video_url,
        folder_path=f"/media/{yt_video_id}",
        media_type="metadata",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


# --- parse_playlist_csv -----------------------------------------------------


def test_parse_playlist_csv_happy_path_matches_real_takeout_format():
    rows = parse_playlist_csv(CSV_SAMPLE)

    assert rows == [
        {"yt_video_id": "yLVcRkFtEcA", "added_at": datetime(2026, 1, 19, 11, 10, 42, tzinfo=UTC)},
        {"yt_video_id": "IOvqN23Sr4o", "added_at": datetime(2026, 1, 19, 11, 10, 48, tzinfo=UTC)},
    ]


def test_parse_playlist_csv_rejects_bad_encoding():
    with pytest.raises(PlaylistCsvError):
        parse_playlist_csv(b"\xff\xfe\xfd\xfc")


def test_parse_playlist_csv_rejects_header_only_file():
    with pytest.raises(PlaylistCsvError):
        parse_playlist_csv("ID vidéo,Code temporel\n".encode("utf-8-sig"))


def test_parse_playlist_csv_dedupes_and_tolerates_bad_timestamp():
    content = (
        "header1,header2\nvid1,not-a-timestamp\nvid1,2026-01-01T00:00:00+00:00\nvid2,\n"
    ).encode("utf-8-sig")

    rows = parse_playlist_csv(content)

    assert rows == [
        {"yt_video_id": "vid1", "added_at": None},
        {"yt_video_id": "vid2", "added_at": None},
    ]


# --- run_playlist_url_import_job --------------------------------------------


def test_run_playlist_url_import_job_continues_past_known_videos(monkeypatch):
    db = make_session()
    known = add_video(db, yt_video_id="vid1", title="Known video")
    playlist = Playlist(
        title="My playlist", source="url", source_url="https://www.youtube.com/playlist?list=PL1"
    )
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", fake_import_video_metadata)

    pages = [
        [
            {"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1", "title": "Known video"},
            {"id": "vid2", "url": "https://www.youtube.com/watch?v=vid2", "title": "New video"},
        ],
        [],
    ]

    def fake_list_playlist_entries(url, page=1, page_size=50):
        return pages[page - 1] if page <= len(pages) else []

    monkeypatch.setattr(playlists_service, "list_playlist_entries", fake_list_playlist_entries)

    playlists_service.run_playlist_url_import_job(job.id, playlist.id)

    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    ).all()
    new_video = db.scalar(select(Video).where(Video.yt_video_id == "vid2"))
    assert [item.video_id for item in items] == [known.id, new_video.id]
    assert db.get(DownloadJob, job.id).status == "metadata"


def test_run_playlist_url_import_job_skips_failing_video_without_aborting(monkeypatch):
    db = make_session()
    playlist = Playlist(
        title="My playlist", source="url", source_url="https://www.youtube.com/playlist?list=PL1"
    )
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)

    def flaky_import(db_, video_url, **kwargs):
        if "bad" in video_url:
            raise ValueError("video unavailable")
        return fake_import_video_metadata(db_, video_url, **kwargs)

    monkeypatch.setattr(playlists_service, "import_video_metadata", flaky_import)
    monkeypatch.setattr(
        playlists_service,
        "list_playlist_entries",
        lambda url, page=1, page_size=50: (
            [
                {"id": "bad1", "url": "https://www.youtube.com/watch?v=bad1"},
                {"id": "good1", "url": "https://www.youtube.com/watch?v=good1"},
            ]
            if page == 1
            else []
        ),
    )

    playlists_service.run_playlist_url_import_job(job.id, playlist.id)

    items = db.scalars(select(PlaylistItem).where(PlaylistItem.playlist_id == playlist.id)).all()
    assert len(items) == 1
    assert db.get(DownloadJob, job.id).status == "metadata"


# --- run_playlist_csv_import_job --------------------------------------------


def test_run_playlist_csv_import_job_sets_position_and_added_at_from_rows(monkeypatch):
    db = make_session()
    playlist = Playlist(title="CSV playlist", source="csv")
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", fake_import_video_metadata)

    rows = [
        {"yt_video_id": "csv1", "added_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"yt_video_id": "csv2", "added_at": datetime(2026, 1, 2, tzinfo=UTC)},
    ]

    run_playlist_csv_import_job(job.id, playlist.id, rows)

    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    ).all()
    assert [item.position for item in items] == [1, 2]
    # SQLite has no native timezone-aware storage, so DateTime(timezone=True)
    # round-trips as naive here even though Postgres (prod) preserves tzinfo.
    assert items[0].added_at.replace(tzinfo=UTC) == datetime(2026, 1, 1, tzinfo=UTC)
    assert db.get(DownloadJob, job.id).status == "metadata"


def test_run_playlist_csv_import_job_skips_dead_row_and_logs_warning(monkeypatch):
    db = make_session()
    playlist = Playlist(title="CSV playlist", source="csv")
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)

    def flaky_import(db_, video_url, **kwargs):
        if "dead" in video_url:
            raise ValueError("video deleted since export")
        return fake_import_video_metadata(db_, video_url, **kwargs)

    monkeypatch.setattr(playlists_service, "import_video_metadata", flaky_import)

    rows = [
        {"yt_video_id": "alive1", "added_at": None},
        {"yt_video_id": "dead1", "added_at": None},
    ]
    run_playlist_csv_import_job(job.id, playlist.id, rows)

    items = db.scalars(select(PlaylistItem).where(PlaylistItem.playlist_id == playlist.id)).all()
    assert len(items) == 1
    warnings = db.scalars(select(DownloadJob).where(DownloadJob.status == "warning")).all()
    assert len(warnings) == 1
    assert db.get(DownloadJob, job.id).status == "metadata"


def test_same_video_reachable_via_two_playlists_creates_one_video_row(monkeypatch):
    db = make_session()
    playlist_a = Playlist(title="A", source="manual")
    playlist_b = Playlist(title="B", source="manual")
    db.add_all([playlist_a, playlist_b])
    db.commit()
    job_a = log_job(db, "queued", "queued")
    job_b = log_job(db, "queued", "queued")

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", fake_import_video_metadata)

    rows = [{"yt_video_id": "shared1", "added_at": None}]
    run_playlist_csv_import_job(job_a.id, playlist_a.id, rows)
    run_playlist_csv_import_job(job_b.id, playlist_b.id, rows)

    videos = db.scalars(select(Video).where(Video.yt_video_id == "shared1")).all()
    assert len(videos) == 1
    items = db.scalars(select(PlaylistItem).where(PlaylistItem.video_id == videos[0].id)).all()
    assert {item.playlist_id for item in items} == {playlist_a.id, playlist_b.id}


# --- routes: manual create / delete -----------------------------------------


def test_create_playlist_manual_creates_row_and_redirects():
    db = make_session()

    response = playlists_routes.create_playlist_manual(title="  My Playlist  ", db=db)

    playlist = db.scalars(select(Playlist)).one()
    assert playlist.title == "My Playlist"
    assert playlist.source == "manual"
    assert response.status_code == 303
    assert response.headers["location"] == f"/playlists/{playlist.id}"


def test_delete_playlist_leaves_video_intact():
    db = make_session()
    playlist = Playlist(title="P", source="manual")
    video = add_video(db)
    db.add(playlist)
    db.commit()
    db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=1))
    db.commit()

    playlists_routes.delete_playlist_route(playlist.id, db=db)

    assert db.get(Playlist, playlist.id) is None
    assert db.get(Video, video.id) is not None
    assert db.scalars(select(PlaylistItem)).all() == []


# --- routes: remove / move items ------------------------------------------


def test_move_and_remove_playlist_items_reorder_positions():
    db = make_session()
    playlist = Playlist(title="P", source="manual")
    v1 = add_video(db, "v1", "V1")
    v2 = add_video(db, "v2", "V2")
    v3 = add_video(db, "v3", "V3")
    db.add(playlist)
    db.commit()
    for position, video in enumerate((v1, v2, v3), start=1):
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=position))
    db.commit()

    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    ).all()
    assert [item.video_id for item in items] == [v1.id, v2.id, v3.id]

    playlists_routes.move_playlist_item(playlist.id, items[2].id, direction="up", db=db)
    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    ).all()
    assert [item.video_id for item in items] == [v1.id, v3.id, v2.id]

    playlists_routes.remove_playlist_item(playlist.id, items[1].id, return_to="", db=db)
    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    ).all()
    assert [item.video_id for item in items] == [v1.id, v2.id]
    assert [item.position for item in items] == [1, 2]


# --- routes: video-detail "add to playlist" ---------------------------------


def test_add_video_to_playlist_existing_and_new_branches():
    db = make_session()
    video = add_video(db)
    playlist = Playlist(title="Existing playlist", source="manual")
    db.add(playlist)
    db.commit()

    playlists_routes.add_video_to_playlist_form(
        video.id, playlist_id=str(playlist.id), new_playlist_title="", return_to="", db=db
    )
    items = db.scalars(select(PlaylistItem).where(PlaylistItem.video_id == video.id)).all()
    assert len(items) == 1
    assert items[0].playlist_id == playlist.id

    playlists_routes.add_video_to_playlist_form(
        video.id, playlist_id="", new_playlist_title="Brand New", return_to="", db=db
    )
    new_playlist = db.scalars(select(Playlist).where(Playlist.title == "Brand New")).one()
    items = db.scalars(select(PlaylistItem).where(PlaylistItem.video_id == video.id)).all()
    assert len(items) == 2
    assert {item.playlist_id for item in items} == {playlist.id, new_playlist.id}


# --- routes: import-url / import-csv (synchronous half only) ---------------


def test_import_playlist_url_route_schedules_background_job(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        playlists_routes,
        "extract_playlist_info",
        lambda url: {"url": url, "title": "Remote Title", "yt_playlist_id": "PL123"},
    )
    scheduled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = playlists_routes.import_playlist_url(
        make_request(),
        background_tasks,
        url="https://www.youtube.com/playlist?list=PL123",
        title="",
        db=db,
    )

    playlist = db.scalars(select(Playlist)).one()
    assert playlist.title == "Remote Title"
    assert playlist.source == "url"
    assert playlist.yt_playlist_id == "PL123"
    assert response.status_code == 303
    assert len(scheduled) == 1
    assert scheduled[0][0] is playlists_service.run_playlist_url_import_job
    assert scheduled[0][1][1] == playlist.id


def test_import_playlist_url_route_reports_not_found(monkeypatch):
    db = make_session()

    def fail(url):
        raise PlaylistNotFoundError(f"Playlist introuvable pour {url}")

    monkeypatch.setattr(playlists_routes, "extract_playlist_info", fail)

    response = playlists_routes.import_playlist_url(
        make_request(), BackgroundTasks(), url="bad", title="", db=db
    )

    assert response.status_code == 303
    assert "level=error" in response.headers["location"]
    assert db.scalars(select(Playlist)).all() == []


def test_import_playlist_csv_route_schedules_background_job_and_derives_title():
    db = make_session()
    scheduled = []
    background_tasks = BackgroundTasks()

    def capture(fn, *args, **kwargs):
        scheduled.append((fn, args, kwargs))

    background_tasks.add_task = capture
    upload = UploadFile(file=io.BytesIO(CSV_SAMPLE), filename="Vidéos de Tech.csv")

    response = playlists_routes.import_playlist_csv(
        make_request(), background_tasks, csv_file=upload, title="", db=db
    )

    playlist = db.scalars(select(Playlist)).one()
    assert playlist.title == "Tech"
    assert playlist.source == "csv"
    assert response.status_code == 303
    assert len(scheduled) == 1
    assert scheduled[0][0] is playlists_service.run_playlist_csv_import_job


def test_import_playlist_csv_route_rejects_bad_csv():
    db = make_session()
    upload = UploadFile(file=io.BytesIO(b"nope"), filename="bad.csv")

    response = playlists_routes.import_playlist_csv(
        make_request(), BackgroundTasks(), csv_file=upload, title="", db=db
    )

    assert response.status_code == 303
    assert "level=error" in response.headers["location"]
    assert db.scalars(select(Playlist)).all() == []


def test_default_playlist_title_from_filename_strips_takeout_prefix():
    assert playlist_title_from_filename("Vidéos de Tech.csv") == "Tech"
    assert playlist_title_from_filename("Videos from Tech.csv") == "Tech"
    assert playlist_title_from_filename("random.csv") == "random"


# --- detail page actions --------------------------------------------------------


def make_playlist_with_videos(db, count=3):
    playlist = Playlist(title="Mix", source="manual")
    db.add(playlist)
    db.commit()
    videos = [add_video(db, f"id{i}", f"Video {chr(ord('C') - i)}") for i in range(count)]
    for position, video in enumerate(videos, start=1):
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=position))
    db.commit()
    db.refresh(playlist)
    return playlist, videos


def ordered_titles(db, playlist):
    items = db.scalars(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    )
    return [item.video.title for item in items]


def test_reorder_playlist_applies_new_order_and_rejects_stale_ids():
    db = make_session()
    playlist, _ = make_playlist_with_videos(db)
    ids = [item.id for item in playlist.items]

    response = playlists_routes.reorder_playlist(
        make_request(headers=[(b"x-requested-with", b"fetch")]),
        playlist.id,
        item_ids=",".join(str(i) for i in [ids[2], ids[0], ids[1]]),
        db=db,
    )
    assert response.status_code == 200
    assert ordered_titles(db, playlist) == ["Video A", "Video C", "Video B"]

    stale = playlists_routes.reorder_playlist(
        make_request(headers=[(b"x-requested-with", b"fetch")]),
        playlist.id,
        item_ids=f"{ids[0]},{ids[1]}",
        db=db,
    )
    assert stale.status_code == 409
    assert ordered_titles(db, playlist) == ["Video A", "Video C", "Video B"]


def test_sort_playlist_by_title_and_reverse():
    db = make_session()
    playlist, _ = make_playlist_with_videos(db)

    playlists_routes.sort_playlist_route(playlist.id, by="title", db=db)
    assert ordered_titles(db, playlist) == ["Video A", "Video B", "Video C"]

    playlists_routes.sort_playlist_route(playlist.id, by="reverse", db=db)
    assert ordered_titles(db, playlist) == ["Video C", "Video B", "Video A"]

    with pytest.raises(HTTPException) as excinfo:
        playlists_routes.sort_playlist_route(playlist.id, by="nope", db=db)
    assert excinfo.value.status_code == 400


def test_rename_and_free_listening_toggle():
    db = make_session()
    playlist, _ = make_playlist_with_videos(db, count=1)

    playlists_routes.rename_playlist_route(playlist.id, title="  Chill  ", db=db)
    assert db.get(Playlist, playlist.id).title == "Chill"

    response = playlists_routes.set_playlist_free_listening(
        make_request(headers=[(b"x-requested-with", b"fetch")]), playlist.id, enabled="1", db=db
    )
    assert response.status_code == 200
    assert db.get(Playlist, playlist.id).free_listening is True


def test_duplicate_playlist_copies_items_as_manual_playlist():
    db = make_session()
    playlist, _ = make_playlist_with_videos(db)
    playlist.source = "url"
    playlist.free_listening = True
    db.commit()

    playlists_routes.duplicate_playlist_route(playlist.id, db=db)

    copy = db.scalar(select(Playlist).where(Playlist.id != playlist.id))
    assert copy.title == "Mix (copie)"
    assert copy.source == "manual"
    assert copy.free_listening is True
    assert ordered_titles(db, copy) == ordered_titles(db, playlist)


def test_export_csv_round_trips_through_the_importer():
    db = make_session()
    playlist, videos = make_playlist_with_videos(db)

    response = playlists_routes.export_playlist_csv(playlist.id, db=db)

    rows = parse_playlist_csv(response.body)
    assert [row["yt_video_id"] for row in rows] == [video.yt_video_id for video in videos]


def test_download_playlist_media_only_queues_missing_files(monkeypatch):
    db = make_session()
    playlist, videos = make_playlist_with_videos(db)
    videos[0].audio_path = "/media/id0/a.m4a"
    db.commit()
    background_tasks = BackgroundTasks()

    response = playlists_routes.download_playlist_media(
        playlist.id, "audio", background_tasks, db=db
    )

    assert response.status_code == 303
    assert len(background_tasks.tasks) == 2
    queued_urls = {task.args[1] for task in background_tasks.tasks}
    assert queued_urls == {videos[1].url, videos[2].url}
    assert all(task.args[2] == ["audio", "metadata"] for task in background_tasks.tasks)


# --- preview before import -------------------------------------------------


class _FakeYoutubeDL:
    def __init__(self, info):
        self._info = info

    def __call__(self, opts):
        self.opts = opts
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if isinstance(self._info, Exception):
            raise self._info
        return self._info


def test_preview_playlist_summarises_entries(monkeypatch):
    db = make_session()
    add_video(db, "known1")
    info = {
        "id": "PL1",
        "title": "Ma playlist",
        "channel": "Une chaîne",
        "webpage_url": "https://www.youtube.com/playlist?list=PL1",
        "entries": [
            {"id": "known1", "title": "A", "duration": 600},
            {"id": "new1", "title": "B", "duration": 1200},
            {"id": "new2", "title": "C", "duration": None},
            {"id": "gone", "title": "[Private video]"},
            None,
        ],
    }
    monkeypatch.setattr(playlists_service, "YoutubeDL", _FakeYoutubeDL(info))

    preview = playlists_service.preview_playlist(db, "https://www.youtube.com/playlist?list=PL1")

    assert preview["title"] == "Ma playlist"
    assert preview["channel_name"] == "Une chaîne"
    assert preview["video_count"] == 3
    assert preview["unavailable_count"] == 1
    assert preview["duration_seconds"] == 1800
    assert preview["unknown_duration_count"] == 1
    assert preview["known_in_library_count"] == 1
    assert preview["sample_titles"] == ["A", "B", "C"]
    assert preview["truncated"] is False
    assert db.scalars(select(Playlist)).all() == []


def test_preview_playlist_rejects_unreadable_url(monkeypatch):
    db = make_session()
    monkeypatch.setattr(playlists_service, "YoutubeDL", _FakeYoutubeDL(RuntimeError("boom")))

    with pytest.raises(PlaylistNotFoundError):
        playlists_service.preview_playlist(db, "https://example.com/nope")
    with pytest.raises(PlaylistNotFoundError):
        playlists_service.preview_playlist(db, "   ")


def test_preview_route_returns_json_and_404(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        playlists_routes,
        "preview_playlist",
        lambda db, url: {"title": "T", "video_count": 2, "duration_seconds": 5400},
    )
    response = playlists_routes.preview_playlist_url(
        url="https://www.youtube.com/playlist?list=PL1", db=db
    )
    assert response.status_code == 200
    assert b'"duration_label":"1 h 30 min"' in response.body

    def fail(db, url):
        raise PlaylistNotFoundError("Playlist introuvable pour bad")

    monkeypatch.setattr(playlists_routes, "preview_playlist", fail)
    response = playlists_routes.preview_playlist_url(url="bad", db=db)
    assert response.status_code == 404


# --- playlist labels, inherited by the videos like a channel's ------------


def test_saving_playlist_labels_labels_only_videos_without_any():
    db = make_session()
    playlist, videos = make_playlist_with_videos(db, count=3)
    videos[0].category_labels = "histoire"
    db.commit()

    playlists_routes.update_playlist_categories(
        playlist.id, preset_categories=["musique"], custom_categories="Chill, musique", db=db
    )

    assert db.get(Playlist, playlist.id).category_labels == "musique,chill"
    labels = {video.title: video.category_labels for video in db.scalars(select(Video))}
    # Videos without labels get the playlist's; one that has its own keeps it.
    assert labels == {"Video C": "histoire", "Video B": "musique,chill", "Video A": "musique,chill"}


def test_clearing_playlist_labels_leaves_the_videos_labels_alone():
    db = make_session()
    playlist, videos = make_playlist_with_videos(db, count=1)
    playlists_routes.update_playlist_categories(
        playlist.id, preset_categories=["musique"], custom_categories="", db=db
    )

    playlists_routes.update_playlist_categories(
        playlist.id, preset_categories=[], custom_categories="", db=db
    )

    assert db.get(Playlist, playlist.id).category_labels is None
    # Same as a channel: the copy is persisted on the video and is no longer the playlist's to take back.
    assert db.get(Video, videos[0].id).category_labels == "musique"


def test_adding_a_video_to_a_labelled_playlist_gives_it_the_labels():
    db = make_session()
    plain = add_video(db, "plain", "Plain")
    labelled = add_video(db, "labelled", "Labelled")
    labelled.category_labels = "science"
    playlist = Playlist(title="Podcasts", source="manual", category_labels="podcasts")
    db.add(playlist)
    db.commit()

    for video in (plain, labelled):
        playlists_routes.add_video_to_playlist_form(
            video.id, playlist_id=str(playlist.id), new_playlist_title="", return_to="", db=db
        )

    assert db.get(Video, plain.id).category_labels == "podcasts"
    assert db.get(Video, labelled.id).category_labels == "science"


def test_url_import_gives_new_videos_the_playlist_labels(monkeypatch):
    db = make_session()
    playlist = Playlist(
        title="Musique",
        source="url",
        source_url="https://www.youtube.com/playlist?list=PL1",
        category_labels="musique",
    )
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")
    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", fake_import_video_metadata)
    pages = [
        [{"id": "vid9", "url": "https://www.youtube.com/watch?v=vid9", "title": "Nouvelle"}],
        [],
    ]
    monkeypatch.setattr(
        playlists_service,
        "list_playlist_entries",
        lambda url, page=1, page_size=50: pages[page - 1] if page <= 2 else [],
    )

    playlists_service.run_playlist_url_import_job(job.id, playlist.id)

    assert db.scalar(select(Video).where(Video.yt_video_id == "vid9")).category_labels == "musique"


def test_duplicate_playlist_keeps_the_labels():
    db = make_session()
    playlist, _ = make_playlist_with_videos(db, count=1)
    playlist.category_labels = "musique"
    db.commit()

    playlists_routes.duplicate_playlist_route(playlist.id, db=db)

    assert (
        db.scalar(select(Playlist).where(Playlist.id != playlist.id)).category_labels == "musique"
    )


def test_run_playlist_url_import_job_stops_at_rate_limit(monkeypatch):
    db = make_session()
    playlist = Playlist(
        title="My playlist", source="url", source_url="https://www.youtube.com/playlist?list=PL1"
    )
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")
    attempted = []

    def limited_import(db_, video_url, **kwargs):
        attempted.append(video_url)
        if "vid2" in video_url:
            raise RateLimitedError("HTTP Error 429: Too Many Requests")
        return fake_import_video_metadata(db_, video_url, **kwargs)

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", limited_import)
    monkeypatch.setattr(
        playlists_service,
        "list_playlist_entries",
        lambda url, page=1, page_size=50: (
            [
                {"id": f"vid{i}", "url": f"https://www.youtube.com/watch?v=vid{i}"}
                for i in range(1, 5)
            ]
            if page == 1
            else []
        ),
    )

    playlists_service.run_playlist_url_import_job(job.id, playlist.id)

    job = db.get(DownloadJob, job.id)
    assert job.status == "failed"
    assert "429" in job.message and "1 vidéo importée" in job.message
    # Nothing is requested after the refusal.
    assert len(attempted) == 2


def test_run_playlist_url_import_job_does_not_refetch_known_videos(monkeypatch):
    db = make_session()
    add_video(db, yt_video_id="vid1", title="Known video")
    playlist = Playlist(
        title="My playlist", source="url", source_url="https://www.youtube.com/playlist?list=PL1"
    )
    db.add(playlist)
    db.commit()
    job = log_job(db, "queued", "queued")
    attempted = []

    def counting_import(db_, video_url, **kwargs):
        attempted.append(video_url)
        return fake_import_video_metadata(db_, video_url, **kwargs)

    monkeypatch.setattr(playlists_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(playlists_service, "import_video_metadata", counting_import)
    monkeypatch.setattr(
        playlists_service,
        "list_playlist_entries",
        lambda url, page=1, page_size=50: (
            [
                {"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"},
                {"id": "vid2", "url": "https://www.youtube.com/watch?v=vid2"},
            ]
            if page == 1
            else []
        ),
    )

    playlists_service.run_playlist_url_import_job(job.id, playlist.id)

    assert attempted == ["https://www.youtube.com/watch?v=vid2"]
    assert db.query(PlaylistItem).filter_by(playlist_id=playlist.id).count() == 2
