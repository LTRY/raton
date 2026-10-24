"""`/api` actions on a channel and the CSV import of YouTube subscriptions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.api import channels as channels_api
from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from tests.users import add_user

CSV_HEADER = "ID des chaînes,URL des chaînes,Titres des chaînes\n"


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


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tasks(monkeypatch):
    """The background jobs the routes queued, instead of running them against a real DB."""
    calls = []
    for name in (
        "run_channel_metadata_import_job",
        "run_channel_profile_refresh_job",
        "run_channel_profile_backfill_job",
    ):
        monkeypatch.setattr(
            channels_api, name, lambda *args, _name=name: calls.append((_name, *args))
        )
    return calls


@pytest.fixture
def channel(db):
    channel = Channel(
        name="Chan",
        url="https://www.youtube.com/@chan",
        yt_channel_id="UCchan",
    )
    db.add(channel)
    db.commit()
    return channel


def test_categories_are_stored_normalized(client, channel):
    response = client.put(
        f"/api/channels/{channel.id}/categories", json={"categories": ["Science", " science "]}
    )

    assert response.status_code == 200
    assert response.json()["categories"] == ["science"]


def test_turning_a_bell_on_syncs_the_catalogue_once(client, db, channel, tasks):
    on = client.put(f"/api/channels/{channel.id}/bells/shorts", json={"enabled": True})
    again = client.put(f"/api/channels/{channel.id}/bells/shorts", json={"enabled": True})
    off = client.put(f"/api/channels/{channel.id}/bells/shorts", json={"enabled": False})

    assert on.json()["channel"]["auto_shorts_enabled"] is True
    assert on.json()["channel"]["auto_metadata_enabled"] is False
    job_id = on.json()["job"]["job_id"]
    assert on.json()["job"]["status_url"] == f"/api/jobs/{job_id}"
    assert db.get(DownloadJob, job_id).message == (
        "Recherche automatique des nouveautés (shorts) de Chan en file d'attente."
    )
    # Already on: nothing to sync. The existing catalogue is not news: the job marks nothing.
    assert again.json()["job"] is None
    assert off.json()["job"] is None
    assert off.json()["channel"]["auto_shorts_enabled"] is False
    assert tasks == [("run_channel_metadata_import_job", job_id, channel.id, 1, "shorts")]


def test_a_bell_is_the_user_s_own(client, db, channel, tasks):
    other = add_user(db, "Invité")

    client.put(
        f"/api/channels/{channel.id}/bells/videos",
        json={"enabled": True},
        headers={"X-Raton-User": str(other.id)},
    )
    mine = client.get(f"/api/channels/{channel.id}").json()
    theirs = client.get(f"/api/channels/{channel.id}", headers={"X-Raton-User": str(other.id)})

    assert mine["auto_metadata_enabled"] is False
    assert theirs.json()["auto_metadata_enabled"] is True


def test_a_bell_section_must_be_videos_or_shorts(client, channel):
    response = client.put(f"/api/channels/{channel.id}/bells/live", json={"enabled": True})

    assert response.status_code == 422


def test_import_metadata_queues_one_page(client, db, channel, tasks):
    default = client.post(f"/api/channels/{channel.id}/import-metadata")
    page = client.post(
        f"/api/channels/{channel.id}/import-metadata", json={"page": 3, "section": "shorts"}
    )

    assert default.status_code == 202
    assert default.json()["message"] == "Import des métadonnées vidéos de Chan en file d'attente."
    assert tasks == [
        ("run_channel_metadata_import_job", default.json()["job_id"], channel.id, 1, "videos"),
        ("run_channel_metadata_import_job", page.json()["job_id"], channel.id, 3, "shorts"),
    ]
    assert (
        client.post(f"/api/channels/{channel.id}/import-metadata", json={"page": 0}).status_code
        == 422
    )


def test_refresh_profile_starts_in_the_background(client, channel, tasks):
    response = client.post(f"/api/channels/{channel.id}/refresh-profile")

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert tasks == [("run_channel_profile_refresh_job", channel.id)]


def test_subscriptions_csv_preview_then_confirm(client, db, channel, tasks):
    csv = (
        CSV_HEADER
        + "UCchan,http://www.youtube.com/channel/UCchan,Chan\n"
        + "UCnew,http://www.youtube.com/channel/UCnew,Nouvelle\n"
    )

    preview = client.post(
        "/api/channels/import-csv", files={"file": ("abonnements.csv", csv, "text/csv")}
    ).json()
    tokens = [row["token"] for row in preview["rows"] if row["token"]]
    confirmed = client.post("/api/channels/import-csv/confirm", json={"tokens": tokens})
    replayed = client.post("/api/channels/import-csv/confirm", json={"tokens": tokens})

    assert (preview["new_count"], preview["existing_count"]) == (1, 1)
    assert [(row["name"], row["already_imported"]) for row in preview["rows"]] == [
        ("Chan", True),
        ("Nouvelle", False),
    ]
    assert confirmed.json() == {"added": 1}
    assert replayed.json() == {"added": 0}
    assert db.query(Channel).filter_by(yt_channel_id="UCnew").one().name == "Nouvelle"
    assert tasks == [("run_channel_profile_backfill_job",)]


def test_subscriptions_csv_preview_refuses_another_file(client, db):
    response = client.post(
        "/api/channels/import-csv", files={"file": ("notes.csv", "a,b\n1,2\n", "text/csv")}
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Format de CSV non reconnu (export des abonnements YouTube attendu)."
    }


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/channels/999/categories", {"categories": []}),
        ("put", "/api/channels/999/bells/videos", {"enabled": True}),
        ("post", "/api/channels/999/import-metadata", None),
        ("post", "/api/channels/999/refresh-profile", None),
    ],
)
def test_actions_refuse_an_unknown_channel(client, db, method, path, body):
    kwargs = {"json": body} if body is not None else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Chaîne introuvable"}
