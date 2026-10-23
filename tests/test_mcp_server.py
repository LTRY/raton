"""The MCP server: read-only tools that forward to the back's `/api`, served in-process."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.video import Video
from mcp_server import api, server


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(api, "_client", TestClient(app))
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_video(db):
    channel = Channel(name="Chaîne", url="https://youtube.com/@c", yt_channel_id="UC-c")
    db.add(channel)
    db.flush()
    video = Video(
        channel_id=channel.id,
        yt_video_id="abc",
        title="Une fiche",
        url="https://youtube.com/watch?v=abc",
        folder_path="/media/abc",
    )
    db.add(video)
    db.commit()
    return channel, video


def test_every_tool_is_read_only_and_listed(db):
    import anyio

    names = {tool.name for tool in anyio.run(server.mcp.list_tools)}
    assert names == {
        "search_library",
        "get_video",
        "list_channels",
        "get_channel",
        "list_playlists",
        "get_playlist",
        "get_nouveautes",
        "get_library_stats",
    }


def test_tools_forward_to_the_api(db):
    channel, video = add_video(db)
    assert server.get_library_stats()["videos"] == 1
    assert server.list_channels()["items"][0]["name"] == "Chaîne"
    assert server.get_channel(channel.id)["name"] == "Chaîne"
    assert server.list_playlists() == []
    detail = server.get_video(video.id)
    assert detail["title"] == "Une fiche"
    assert "subtitles_vtt" not in detail
    assert server.search_library(q="fiche")["total"] == 1
    assert "stacks" in server.get_nouveautes()


def test_a_refused_call_raises_the_back_message(db):
    with pytest.raises(api.ApiError) as error:
        server.get_video(999)
    assert str(error.value)
