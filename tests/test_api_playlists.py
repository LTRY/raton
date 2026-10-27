"""`/api/playlists`: reading, importing and editing playlists."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.api import playlists as playlists_api
from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.playlist import Playlist, PlaylistItem
from back.models.video import Video
from back.services.jobs import playlists as playlists_jobs
from back.services.playlists import imports as playlists_imports
from tests.site import site_client
from tests.users import add_user, set_video_state, user_id

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
    yield session
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return site_client()


@pytest.fixture
def tasks(monkeypatch):
    """The background jobs the routes queued, instead of running them against a real DB."""
    calls = []
    for name in (
        "run_playlist_url_import_job",
        "run_playlist_csv_import_job",
        "run_media_download_job",
    ):
        monkeypatch.setattr(
            playlists_api, name, lambda *args, _name=name: calls.append((_name, *args))
        )
    return calls


def add_videos(db, count, prefix="v"):
    channel = Channel(
        name="Chan", url=f"https://youtube.com/@{prefix}", yt_channel_id=f"UC{prefix}"
    )
    db.add(channel)
    db.flush()
    videos = []
    for index in range(count):
        video = Video(
            channel_id=channel.id,
            yt_video_id=f"{prefix}{index}",
            title=f"Titre {index}",
            url=f"https://youtube.com/watch?v={prefix}{index}",
            folder_path=f"/media/{prefix}{index}",
            duration_seconds=100 * (index + 1),
        )
        db.add(video)
        videos.append(video)
    db.commit()
    return videos


def add_playlist(db, videos, **fields):
    playlist = Playlist(
        user_id=user_id(db),
        title=fields.pop("title", "Écoute"),
        source=fields.pop("source", "manual"),
        **fields,
    )
    db.add(playlist)
    db.flush()
    for position, video in enumerate(videos, start=1):
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=position))
    db.commit()
    return playlist


def test_create_then_read_a_playlist(client, db):
    videos = add_videos(db, 2)
    videos[0].audio_path = "/media/v0/a.m4a"
    db.commit()
    set_video_state(db, videos[1], watched_at=NOW)

    created = client.post("/api/playlists", json={"title": "  Écoute  "})
    playlist_id = created.json()["id"]
    for video in videos:
        client.post(f"/api/playlists/{playlist_id}/items", json={"video_id": video.id})
    again = client.post(f"/api/playlists/{playlist_id}/items", json={"video_id": videos[0].id})
    detail = client.get(f"/api/playlists/{playlist_id}").json()

    assert created.status_code == 201
    assert created.json()["title"] == "Écoute"
    assert len(again.json()["items"]) == 2
    assert detail["stats"] == {
        "count": 2,
        "total_duration_seconds": 300,
        "seen_count": 1,
        "missing_audio": 1,
        "missing_video": 2,
    }
    first = detail["items"][0]
    assert (first["position"], first["video_id"], first["channel_name"]) == (
        1,
        videos[0].id,
        "Chan",
    )
    assert (first["has_audio"], first["has_video"], first["seen"]) == (True, False, False)


def test_a_playlist_is_its_user_s_own(client, db):
    mine = add_playlist(db, add_videos(db, 1), title="La mienne")
    other = add_user(db, "Invité")
    as_other = {"X-Raton-User": str(other.id)}

    created = client.post("/api/playlists", json={"title": "La leur"}, headers=as_other).json()
    listed = [playlist["title"] for playlist in client.get("/api/playlists").json()]
    listed_by_other = [
        playlist["title"] for playlist in client.get("/api/playlists", headers=as_other).json()
    ]

    assert listed == ["La mienne"]
    assert listed_by_other == ["La leur"]
    # Another user's playlist is as unknown as a deleted one, to read or to edit.
    assert client.get(f"/api/playlists/{created['id']}").status_code == 404
    assert client.delete(f"/api/playlists/{mine.id}", headers=as_other).status_code == 404


def test_create_refuses_a_blank_title(client, db):
    response = client.post("/api/playlists", json={"title": "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "Le titre est obligatoire."}


def test_list_gives_counts_and_covers_in_constant_queries(client, db):
    small = add_playlist(db, add_videos(db, 1, "a"), title="Petite")
    client.get("/api/playlists")
    db.statements.clear()
    client.get("/api/playlists")
    one_playlist = len(db.statements)
    for index in range(5):
        add_playlist(db, add_videos(db, 3, f"p{index}"), title=f"P{index}")
    db.statements.clear()

    payload = client.get("/api/playlists").json()

    assert len(db.statements) == one_playlist
    assert len(payload) == 6
    entry = next(item for item in payload if item["id"] == small.id)
    assert entry["item_count"] == 1
    assert entry["cover_video_id"] == small.items[0].video_id


def test_edit_title_categories_and_free_listening(client, db):
    videos = add_videos(db, 2)
    playlist = add_playlist(db, videos)
    videos[1].category_labels = "déjà"
    db.commit()

    renamed = client.put(f"/api/playlists/{playlist.id}/title", json={"title": " Chill "})
    blank = client.put(f"/api/playlists/{playlist.id}/title", json={"title": ""})
    labels = client.put(f"/api/playlists/{playlist.id}/categories", json={"categories": ["Jazz"]})
    free = client.put(f"/api/playlists/{playlist.id}/free-listening", json={"enabled": True})

    assert renamed.json()["title"] == "Chill"
    assert blank.status_code == 400
    assert labels.json()["playlist"]["categories"] == ["jazz"]
    assert labels.json()["labelled_count"] == 2
    db.refresh(videos[1])
    assert videos[1].category_labels == "déjà,jazz"
    assert free.json()["free_listening"] is True


def test_order_sort_move_and_remove_items(client, db):
    videos = add_videos(db, 3)
    playlist = add_playlist(db, videos)
    ids = [item.id for item in playlist.items]

    reordered = client.put(f"/api/playlists/{playlist.id}/order", json={"item_ids": ids[::-1]})
    stale = client.put(f"/api/playlists/{playlist.id}/order", json={"item_ids": ids[:2]})
    by_duration = client.post(f"/api/playlists/{playlist.id}/sort", json={"by": "duration"})
    bad_sort = client.post(f"/api/playlists/{playlist.id}/sort", json={"by": "nope"})
    moved = client.post(
        f"/api/playlists/{playlist.id}/items/{ids[2]}/move", json={"direction": "up"}
    )
    removed = client.delete(f"/api/playlists/{playlist.id}/items/{ids[0]}")
    foreign = client.delete(f"/api/playlists/{playlist.id + 1}/items/{ids[1]}")
    detail = client.get(f"/api/playlists/{playlist.id}").json()

    assert [item["item_id"] for item in reordered.json()["items"]] == ids[::-1]
    assert stale.status_code == 409
    assert [item["item_id"] for item in by_duration.json()["items"]] == ids
    assert bad_sort.status_code == 400
    assert bad_sort.json() == {"detail": "Tri inconnu"}
    assert [item["item_id"] for item in moved.json()["items"]] == [ids[0], ids[2], ids[1]]
    assert removed.status_code == 204
    assert foreign.status_code == 404
    assert [(item["item_id"], item["position"]) for item in detail["items"]] == [
        (ids[2], 1),
        (ids[1], 2),
    ]


def test_import_url_creates_the_playlist_and_queues_its_videos(client, db, tasks, monkeypatch):
    monkeypatch.setattr(
        playlists_jobs,
        "extract_playlist_info",
        lambda url: {"url": url, "title": "Titre YouTube", "yt_playlist_id": "PL1"},
    )

    response = client.post(
        "/api/playlists/import-url", json={"url": "https://youtube.com/playlist?list=PL1"}
    )

    assert response.status_code == 202
    playlist = response.json()["playlist"]
    assert (playlist["title"], playlist["source"], playlist["yt_playlist_id"]) == (
        "Titre YouTube",
        "url",
        "PL1",
    )
    assert tasks == [
        ("run_playlist_url_import_job", response.json()["job"]["job_id"], playlist["id"])
    ]


def test_import_url_reports_an_unknown_playlist(client, db, monkeypatch):
    def fail(url):
        raise playlists_imports.PlaylistNotFoundError(f"Playlist introuvable pour {url}")

    monkeypatch.setattr(playlists_jobs, "extract_playlist_info", fail)

    response = client.post("/api/playlists/import-url", json={"url": "bad"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Playlist introuvable pour bad"}
    assert db.query(Playlist).count() == 0


def test_import_csv_titles_the_playlist_from_the_file_name(client, db, tasks):
    csv = "ID vidéo,Code temporel\nabc,2026-01-01T00:00:00+00:00\n".encode("utf-8-sig")

    response = client.post(
        "/api/playlists/import-csv", files={"file": ("Vidéos de Tech.csv", csv, "text/csv")}
    )
    refused = client.post(
        "/api/playlists/import-csv", files={"file": ("x.csv", b"nope", "text/csv")}
    )

    assert response.status_code == 202
    assert response.json()["playlist"]["title"] == "Tech"
    assert tasks[0][0] == "run_playlist_csv_import_job"
    assert tasks[0][3] == [{"yt_video_id": "abc", "added_at": datetime(2026, 1, 1, tzinfo=UTC)}]
    assert refused.status_code == 400


def test_refresh_only_a_playlist_imported_from_a_url(client, db, tasks):
    manual = add_playlist(db, [])
    from_url = add_playlist(db, [], source="url", source_url="https://youtube.com/playlist?list=PL")

    refused = client.post(f"/api/playlists/{manual.id}/refresh")
    started = client.post(f"/api/playlists/{from_url.id}/refresh")

    assert refused.status_code == 400
    assert refused.json() == {
        "detail": "Seule une playlist importée depuis une URL peut être rafraîchie."
    }
    assert started.status_code == 202
    assert tasks == [("run_playlist_url_import_job", started.json()["job_id"], from_url.id)]


def test_download_queues_one_job_per_video_missing_the_format(client, db, tasks):
    videos = add_videos(db, 3)
    videos[0].audio_path = "/media/v0/a.m4a"
    db.commit()
    playlist = add_playlist(db, videos)

    response = client.post(f"/api/playlists/{playlist.id}/download/audio")
    refused = client.post(f"/api/playlists/{playlist.id}/download/subtitles")

    assert response.status_code == 202
    jobs = response.json()["jobs"]
    assert [db.get(DownloadJob, job["job_id"]).video_id for job in jobs] == [
        videos[1].id,
        videos[2].id,
    ]
    assert tasks == [
        ("run_media_download_job", jobs[0]["job_id"], videos[1].url, "audio"),
        ("run_media_download_job", jobs[1]["job_id"], videos[2].url, "audio"),
    ]
    assert refused.status_code == 400


def test_duplicate_and_delete_never_touch_the_videos(client, db):
    videos = add_videos(db, 2)
    playlist = add_playlist(db, videos)

    copy = client.post(f"/api/playlists/{playlist.id}/duplicate")
    deleted = client.delete(f"/api/playlists/{playlist.id}")

    assert copy.status_code == 201
    assert copy.json()["title"] == "Écoute (copie)"
    assert deleted.status_code == 204
    assert client.get(f"/api/playlists/{copy.json()['id']}").json()["stats"]["count"] == 2
    assert db.query(Video).count() == 2


def test_preview_reports_an_unknown_playlist(client, db, monkeypatch):
    def fail(db_, url):
        raise playlists_imports.PlaylistNotFoundError("URL de playlist manquante.")

    monkeypatch.setattr(playlists_api, "preview_playlist", fail)

    response = client.post("/api/playlists/preview", json={"url": ""})

    assert response.status_code == 404
    assert response.json() == {"detail": "URL de playlist manquante."}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/playlists/999", None),
        ("delete", "/api/playlists/999", None),
        ("put", "/api/playlists/999/title", {"title": "x"}),
        ("post", "/api/playlists/999/duplicate", None),
        ("post", "/api/playlists/999/items", {"video_id": 1}),
    ],
)
def test_routes_refuse_an_unknown_playlist(client, db, method, path, body):
    kwargs = {"json": body} if body is not None else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Playlist introuvable"}


def test_adding_an_unknown_fiche_is_refused(client, db):
    playlist = add_playlist(db, [])

    response = client.post(f"/api/playlists/{playlist.id}/items", json={"video_id": 999})

    assert response.status_code == 404
    assert response.json() == {"detail": "Vidéo introuvable"}


def test_export_csv_is_the_takeout_layout_import_csv_reads_back(client, db, tasks):
    videos = add_videos(db, 2)
    playlist = add_playlist(db, videos)

    response = client.get(f"/api/playlists/{playlist.id}/export.csv")
    imported = client.post(
        "/api/playlists/import-csv",
        files={"file": ("Vidéos de Copie.csv", response.content, "text/csv")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="playlist-{playlist.id}.csv"'
    )
    assert imported.json()["playlist"]["title"] == "Copie"
    rows = tasks[0][3]
    assert [row["yt_video_id"] for row in rows] == [video.yt_video_id for video in videos]
    assert client.get("/api/playlists/999/export.csv").status_code == 404


@pytest.mark.parametrize("path", ["/playlists/{id}/export.csv", "/api/playlists/{id}/export.csv"])
def test_export_csv_cost_does_not_grow_with_the_playlist(client, db, path):
    small = add_playlist(db, add_videos(db, 2, "s"))
    large = add_playlist(db, add_videos(db, 40, "l"))
    counts = []
    for playlist in (small, large):
        db.expunge_all()
        db.statements.clear()
        assert client.get(path.format(id=playlist.id)).status_code == 200
        counts.append(len(db.statements))

    assert counts[0] == counts[1]


def test_preview_summarises_a_playlist_url_in_raw_values(client, db, monkeypatch):
    summary = {
        "url": "https://youtube.com/playlist?list=PL1",
        "title": "Cours",
        "yt_playlist_id": "PL1",
        "channel_name": "Chan",
        "video_count": 2,
        "unavailable_count": 1,
        "duration_seconds": 5400.5,
        "unknown_duration_count": 0,
        "known_in_library_count": 1,
        "sample_titles": ["A", "B"],
        "truncated": False,
    }
    monkeypatch.setattr(playlists_api, "preview_playlist", lambda db_, url: summary)

    response = client.post("/api/playlists/preview", json={"url": summary["url"]})

    assert response.status_code == 200
    assert response.json() == summary
