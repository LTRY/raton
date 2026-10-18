"""Turbo cache behavior of the playlist pages (`playlists.html`, `playlist_detail.html`)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.playlist import Playlist


@pytest.fixture
def client_and_playlist():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    playlist = Playlist(title="Ma playlist", source="manual")
    db.add(playlist)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), playlist
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/playlists", "/playlists/{id}"])
def test_playlist_pages_opt_out_of_turbo_preview(client_and_playlist, path):
    # A cached preview would replay the entrance animation when the fresh page replaces it,
    # which looks like the page loading twice.
    client, playlist = client_and_playlist
    html = client.get(path.format(id=playlist.id)).text
    assert '<meta name="turbo-cache-control" content="no-preview">' in html


def test_playlist_detail_shows_and_edits_labels(client_and_playlist):
    client, playlist = client_and_playlist
    playlist.category_labels = "musique,chill"

    html = client.get(f"/playlists/{playlist.id}").text

    assert f'action="/playlists/{playlist.id}/categories"' in html
    assert html.count('class="category-label"') >= 2
    assert ">chill<" in html


def test_playlist_rows_have_no_number_and_play_from_the_row(client_and_playlist):
    # The row number was replaced by whole-row playback (spec 11, "Lignes"):
    # no `.pld-num`, and a "⋯" menu for the actions on a phone.
    from app.models.playlist import PlaylistItem
    from app.models.video import Video

    client, playlist = client_and_playlist
    db = app.dependency_overrides[get_db]()
    video = Video(
        yt_video_id="abc", title="Piste", url="https://youtu.be/abc", folder_path="/tmp/none"
    )
    db.add(video)
    db.flush()
    db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=0))
    db.commit()

    html = client.get(f"/playlists/{playlist.id}").text

    assert "pld-num" not in html
    assert "data-more" in html
    assert 'class="pld-fiche"' in html
    # The grip is hidden on a phone: the menu carries the reorder entries.
    assert 'data-move="up"' in html
    assert 'data-move="down"' in html
