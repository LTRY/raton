"""A media stream must give its DB connection back before the file is sent: a player keeps the
stream open for as long as it plays (or stays paused), and the pool is small."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.api import media
from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.video import Video


@pytest.fixture
def session_log(monkeypatch):
    """The session the routes get, and the list its `close()` writes to."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    events: list[str] = []
    real_close = session.close

    def recording_close():
        events.append("session closed")
        real_close()

    monkeypatch.setattr(session, "close", recording_close)

    def tracked_db():
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = tracked_db
    yield session, events
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_stream_releases_its_session_before_sending_the_file(
    session_log, tmp_path, monkeypatch, kind
):
    session, events = session_log
    file = tmp_path / ("track.m4a" if kind == "audio" else "film.mp4")
    file.write_bytes(b"0123456789")
    video = Video(
        yt_video_id="abc",
        title="Titre",
        url="https://www.youtube.com/watch?v=abc",
        folder_path=str(tmp_path),
        **{f"{kind}_path": str(file)},
    )
    session.add(video)
    session.commit()
    real_ranges = media.file_byte_ranges

    def recording_ranges(*args, **kwargs):
        events.append("first byte sent")
        yield from real_ranges(*args, **kwargs)

    monkeypatch.setattr(media, "file_byte_ranges", recording_ranges)

    response = TestClient(app).get(f"/api/videos/{video.id}/{kind}", headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    # The second close is `get_db`'s own, once the response is over: a no-op by then.
    assert events[:2] == ["session closed", "first byte sent"]


def test_every_media_route_releases_the_session():
    for route in media.router.routes:
        released = [
            dependency
            for dependency in route.dependant.dependencies
            if dependency.call is media.release_db_before_body
        ]
        assert released and released[0].scope == "function", route.path
