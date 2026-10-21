"""The front's plumbing: pages rendered from `/api`, the `/api` relay, the back's errors."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.video import Video
from front.records import record


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_a_page_is_rendered_from_the_api(front_client):
    client = front_client(make_session())

    response = client.get("/raton/variations")

    assert response.status_code == 200
    assert "Toutes les phrases de Raton" in response.text


def test_the_relay_passes_api_calls_and_their_errors_through(front_client):
    db = make_session()
    db.add(Video(yt_video_id="a", title="Une fiche", url="u", folder_path="f"))
    db.commit()
    client = front_client(db)

    found = client.get("/api/videos/1")
    missing = client.put("/api/videos/9/rating", json={"rating": 3})

    assert found.json()["title"] == "Une fiche"
    assert (missing.status_code, missing.json()) == (404, {"detail": "Vidéo introuvable"})


def test_the_relay_refuses_a_cross_site_write_like_the_back(front_client):
    client = front_client(make_session())

    response = client.put(
        "/api/videos/1/rating", json={"rating": 3}, headers={"origin": "https://evil.test"}
    )

    assert response.status_code == 403


def test_the_relay_streams_a_range_of_a_media_file(front_client, tmp_path):
    audio = tmp_path / "a.m4a"
    audio.write_bytes(bytes(range(100)))
    db = make_session()
    db.add(
        Video(
            yt_video_id="a",
            title="Une fiche",
            url="u",
            folder_path=str(tmp_path),
            audio_path=str(audio),
        )
    )
    db.commit()
    client = front_client(db)

    response = client.get("/api/videos/1/audio", headers={"range": "bytes=10-19"})

    assert response.status_code == 206
    assert response.content == bytes(range(10, 20))
    assert response.headers["content-range"] == "bytes 10-19/100"


def test_an_unknown_fiche_page_answers_the_api_status_and_detail(front_client):
    client = front_client(make_session())

    response = client.get("/videos/9")

    assert (response.status_code, response.json()) == (404, {"detail": "Vidéo introuvable"})


def test_records_turn_iso_datetimes_into_datetimes_and_keep_plain_dates():
    data = record(
        {"items": [{"at": "2026-10-21T08:30:00+00:00"}], "day": "2026-10-21", "title": "x"}
    )

    assert data.items[0].at == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
    assert data["day"] == "2026-10-21"
    assert data.get("missing", 1) == 1


def test_import_sheet_carries_only_the_import_of_its_page(front_client):
    client = front_client(make_session())
    expected = {
        "/channels": {"/channels", "/channels/import-csv"},
        "/playlists": {"/playlists", "/playlists/import-url", "/playlists/import-csv"},
        "/videos": {"/videos/download", "/videos/upload"},
        "/dashboard/nouveautes": {"/videos/download", "/videos/upload"},
    }
    every = {a for actions in expected.values() for a in actions}
    for path, actions in expected.items():
        html = client.get(path).text
        assert "data-import-fab" in html, path
        for action in every:
            assert (f'action="{action}"' in html) == (action in actions), (path, action)


def test_import_query_opens_the_sheet_of_its_page(front_client):
    client = front_client(make_session())
    assert "data-import-fab open" in client.get("/videos?import=video").text
    assert "data-import-fab open" in client.get("/playlists?import=playlist").text
    assert "data-import-fab open" not in client.get("/videos").text


def test_import_categories_frame(front_client):
    html = front_client(make_session()).get("/import/categories").text
    assert '<turbo-frame id="import-categories">' in html


def test_import_button_only_on_chaines_playlists_and_bibliotheque(front_client):
    client = front_client(make_session())
    for path in (
        "/channels",
        "/playlists",
        "/videos",
        "/dashboard/nouveautes",
        "/dashboard/historique",
    ):
        assert "data-import-fab" in client.get(path).text, path
    for path in ("/settings", "/", "/stats"):
        assert "data-import-fab" not in client.get(path).text, path
