"""`/api/channels` (list, detail, rating) and the `categories` field of the `/api` reads."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.channels.listing import CHANNEL_PAGE_SIZE

NOW = datetime(2026, 10, 9, tzinfo=UTC)
RATING_REFUSED = {"detail": "La note doit être comprise entre 0 et 5."}


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
    return TestClient(app)


def add_channel(db, name, **fields):
    channel = Channel(
        name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}", **fields
    )
    db.add(channel)
    db.flush()
    return channel


def add_video(db, channel, key, **fields):
    video = Video(
        channel_id=channel.id if channel else None,
        yt_video_id=key,
        title=key,
        url=f"https://youtube.com/watch?v={key}",
        folder_path=f"/media/{key}",
        **fields,
    )
    db.add(video)
    db.flush()
    return video


def test_list_pages_every_channel_with_its_counts(client, db):
    for index in range(CHANNEL_PAGE_SIZE + 2):
        add_channel(db, f"c{index:03d}", rating=0, created_at=NOW - timedelta(hours=index))
    played = add_channel(db, "joue", rating=4, category_labels="science,cuisine")
    add_video(db, played, "a")
    add_video(db, played, "b")
    db.add(DownloadJob(status="played", message="{}", channel_id=played.id, created_at=NOW))
    db.commit()

    first = client.get("/api/channels").json()
    second = client.get("/api/channels?page=2").json()

    assert (first["sort"], first["page"], first["total_pages"], first["total"]) == (
        "activity",
        1,
        2,
        CHANNEL_PAGE_SIZE + 3,
    )
    assert len(first["items"]) == CHANNEL_PAGE_SIZE
    assert len(second["items"]) == 3
    # The "activity" sort puts the channel last played first.
    top = first["items"][0]
    assert top["name"] == "joue"
    assert top["video_count"] == 2
    assert top["categories"] == ["science", "cuisine"]
    assert top["last_played_at"].startswith("2026-10-09")
    assert first["items"][1]["last_played_at"] is None


def test_list_sorts_filters_and_searches_like_the_channels_page(client, db):
    add_channel(db, "Alpha", rating=0)
    add_channel(db, "Bravo Histoire", rating=5)
    add_channel(db, "Charlie", rating=2)
    db.commit()

    alpha = client.get("/api/channels?sort=alpha").json()
    by_rating = client.get("/api/channels?sort=rating").json()
    rated = client.get("/api/channels?rated=true").json()
    found = client.get("/api/channels?q=%20%20histoire%20").json()
    bogus = client.get("/api/channels?sort=bogus").json()

    assert [item["name"] for item in alpha["items"]] == ["Alpha", "Bravo Histoire", "Charlie"]
    assert [item["name"] for item in by_rating["items"]] == ["Bravo Histoire", "Charlie", "Alpha"]
    assert [item["name"] for item in rated["items"]] == ["Bravo Histoire", "Charlie"]
    assert [item["name"] for item in found["items"]] == ["Bravo Histoire"]
    assert bogus["sort"] == "activity"


def test_list_counts_fiches_for_the_page_only_in_constant_queries(client, db):
    def channels_with_videos(prefix, count):
        for index in range(count):
            channel = add_channel(db, f"{prefix}{index}")
            add_video(db, channel, f"{prefix}{index}-v")
        db.commit()

    channels_with_videos("a", 2)
    db.statements.clear()
    client.get("/api/channels")
    small = len(db.statements)
    channels_with_videos("b", 20)
    db.statements.clear()

    client.get("/api/channels")

    assert len(db.statements) == small


def test_detail_gives_the_profile_and_its_image_routes(client, db):
    channel = add_channel(
        db,
        "Chan",
        description="Une chaîne.",
        keywords=json.dumps(["histoire", "", "cartes"]),
        avatar_path="/media/_channels/UC-Chan/avatar.jpg",
        category_labels="histoire",
    )
    add_video(db, channel, "v")
    db.commit()

    payload = client.get(f"/api/channels/{channel.id}").json()

    assert payload["description"] == "Une chaîne."
    assert payload["keywords"] == ["histoire", "cartes"]
    assert payload["categories"] == ["histoire"]
    assert payload["avatar_url"] == f"/channels/{channel.id}/avatar"
    assert payload["banner_url"] is None
    assert payload["video_count"] == 1


def test_rating_a_channel_or_a_fiche(client, db):
    channel = add_channel(db, "Chan", rating=1)
    video = add_video(db, channel, "v")
    db.commit()

    channel_rated = client.put(f"/api/channels/{channel.id}/rating", json={"rating": 5})
    video_rated = client.put(f"/api/videos/{video.id}/rating", json={"rating": 0})
    too_high = client.put(f"/api/videos/{video.id}/rating", json={"rating": 9})
    negative = client.put(f"/api/channels/{channel.id}/rating", json={"rating": -1})

    assert channel_rated.json()["rating"] == 5
    assert set(channel_rated.json()) >= {
        "categories",
        "auto_metadata_enabled",
        "auto_shorts_enabled",
    }
    assert video_rated.json()["rating"] == 0
    assert set(video_rated.json()) >= {"is_new", "list_state", "categories", "comment"}
    assert (too_high.status_code, too_high.json()) == (400, RATING_REFUSED)
    assert (negative.status_code, negative.json()) == (400, RATING_REFUSED)
    db.refresh(channel)
    assert channel.rating == 5


def test_adding_a_channel_refuses_an_out_of_range_rating_in_french(client, db):
    response = client.post("/api/channels", json={"url": "@chan", "rating": 7})

    assert (response.status_code, response.json()) == (400, RATING_REFUSED)


def test_fiche_reads_give_categories_as_a_list(client, db):
    channel = add_channel(db, "Chan")
    video = add_video(
        db, channel, "v", category_labels="science, Cuisine", video_path="/media/v/v.mp4"
    )
    bare = add_video(db, channel, "w", video_path="/media/w/v.mp4")
    db.commit()

    listed = {item["id"]: item for item in client.get("/api/videos").json()["items"]}
    library = {item["id"]: item for item in client.get("/api/library").json()["items"]}
    detail = client.get(f"/api/videos/{video.id}").json()

    assert listed[video.id]["categories"] == ["science", "cuisine"]
    assert listed[bare.id]["categories"] == []
    assert library[video.id]["categories"] == ["science", "cuisine"]
    assert detail["categories"] == ["science", "cuisine"]
    assert "category_labels" not in detail
