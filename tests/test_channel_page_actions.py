from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.video import Video
from tests.site import site_client


def make_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    channel = Channel(name="Ma chaîne", url="https://youtube.com/@ma", yt_channel_id="UC1")
    db.add(channel)
    db.flush()
    db.add(
        Video(
            channel_id=channel.id,
            yt_video_id="v1",
            title="Une vidéo",
            url="https://youtu.be/v1",
            folder_path="/x",
            media_type="metadata",
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    return site_client(), db, channel


def test_channel_page_shows_both_bells_and_a_delete_warning():
    client, db, channel = make_client()
    try:
        html = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()
    assert html.count(f'action="/channels/{channel.id}/auto-metadata"') == 2
    assert 'name="section" value="shorts"' in html
    assert "Cette action est définitive" in html
    assert "1 fiche vidéo/short" in html
    assert f'action="/channels/{channel.id}/delete"' in html


def test_channels_page_cards_show_the_fiche_count_and_both_bells():
    client, db, channel = make_client()
    try:
        html = client.get("/channels?rated=false").text
    finally:
        app.dependency_overrides.clear()
    assert '<article class="channel-card">' in html
    assert ">1</span>" in html and "channel-card-count" in html
    assert html.count(f'action="/channels/{channel.id}/auto-metadata"') == 2
    assert html.count("data-bell-form") == 2
    assert 'class="channel-bell-btn"' in html


def test_deleting_a_channel_removes_its_videos():
    client, db, channel = make_client()
    try:
        response = client.post(
            f"/channels/{channel.id}/delete", data={"next": "/channels"}, follow_redirects=False
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 303
    assert db.scalars(select(Video)).all() == []
