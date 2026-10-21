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


def test_import_button_is_on_every_page_with_the_three_imports(front_client):
    html = front_client(make_session()).get("/channels").text
    assert "data-import-fab" in html
    for href in ("/videos/import", "/playlists#pl-add", "/channels?import=abonnements"):
        assert f'href="{href}"' in html


def test_channels_import_link_opens_the_csv_menu(front_client):
    html = front_client(make_session()).get("/channels?import=abonnements").text
    assert 'class="page-actions-menu" open' in html
    assert 'class="page-action" open' in html
