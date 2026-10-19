"""`detail_view`: what the page of a fiche shows, called without HTTP."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.playlist import Playlist
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.services.videos.detail_view import VideoNotFoundError, open_video_detail


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(db, tmp_path, metadata=None, **fields):
    folder = tmp_path / "fiche"
    folder.mkdir()
    if metadata is not None:
        (folder / "metadata.json").write_text(metadata, encoding="utf-8")
        fields["metadata_path"] = str(folder / "metadata.json")
    video = Video(
        yt_video_id="v",
        title="Fiche",
        url="https://youtube.com/watch?v=v",
        folder_path=str(folder),
        **fields,
    )
    db.add(video)
    db.commit()
    return video


def test_open_video_detail_returns_raw_values_and_takes_the_fiche_out_of_nouveautes(db, tmp_path):
    metadata = {
        "description": "Desc",
        "tags": ["a", ""],
        "chapters": [{"title": "Intro", "start_time": 125.5}, {"start_time": 3}],
        "duration": 3725,
        "view_count": 1234567,
        "uploader": "Moi",
    }
    video = add_video(db, tmp_path, json.dumps(metadata), is_new=True)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=10,
            end_seconds=40,
            source="sponsorblock",
        )
    )
    db.add_all([Playlist(title="B", source="manual"), Playlist(title="A", source="manual")])
    db.commit()

    detail = open_video_detail(db, video.id)

    assert detail.video.is_new is False
    assert detail.metadata == {
        "description": "Desc",
        "tags": ["a"],
        "chapters": [{"title": "Intro", "start_seconds": 125.5}],
        "duration": 3725,
        "view_count": 1234567,
        "like_count": None,
        "comment_count": None,
        "uploader": "Moi",
    }
    assert [row.category for row in detail.sponsor_segments] == ["sponsor"]
    assert detail.skip_segments == [{"start": 10.0, "end": 40.0}]
    assert detail.sponsor_skip_enabled is True
    assert [playlist.title for playlist in detail.all_playlists] == ["A", "B"]
    assert detail.subtitles_vtt is None
    assert detail.documents["transcript"] is None


def test_open_video_detail_tolerates_an_unreadable_metadata_file(db, tmp_path):
    video = add_video(db, tmp_path, "{not json")

    detail = open_video_detail(db, video.id)

    assert detail.metadata["description"] is None
    assert detail.metadata["chapters"] == []


def test_open_video_detail_refuses_an_unknown_fiche(db):
    with pytest.raises(VideoNotFoundError, match="Vidéo introuvable"):
        open_video_detail(db, 999)
