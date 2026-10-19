import io

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.setting import AppSetting
from app.models.video import Video
from app.services.media import local_upload
from app.services.media.local_upload import LocalUploadError, import_local_media
from app.web.routes import videos as videos_routes


def make_session(media_root):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(AppSetting(key="media_root", value=str(media_root)))
    db.commit()
    return db


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr(local_upload, "_probe_duration_seconds", lambda path: 42)
    monkeypatch.setattr(local_upload, "_extract_thumbnail", lambda video, target, duration: False)


def test_audio_file_creates_a_local_video(tmp_path):
    db = make_session(tmp_path)
    video, created = import_local_media(db, "Mon Podcast.mp3", io.BytesIO(b"abc"))

    assert created
    assert video.audio_path and video.video_path is None
    assert video.media_type == "audio"
    assert video.title == "Mon Podcast"
    # sqlite does not enforce the Postgres check constraint, so pin the allowed values here.
    assert video.download_source in {"auto", "manual"}
    assert video.duration_seconds == 42
    assert video.file_size_bytes == 3
    assert (
        tmp_path / "Local" / video.audio_path.split("/")[-2] / "Mon Podcast.mp3"
    ).read_bytes() == b"abc"
    assert db.get(Channel, video.channel_id).name == "Fichiers locaux"
    # No staging folder is left behind.
    assert [p.name for p in (tmp_path / "Local").iterdir()] == [video.folder_path.split("/")[-1]]


def test_same_content_is_not_imported_twice(tmp_path):
    db = make_session(tmp_path)
    first, _ = import_local_media(db, "a.mp4", io.BytesIO(b"same"))
    second, created = import_local_media(db, "b.mp4", io.BytesIO(b"same"))

    assert not created
    assert second.id == first.id
    assert len(db.scalars(select(Video)).all()) == 1
    assert len(list((tmp_path / "Local").iterdir())) == 1


def test_unsupported_and_empty_files_are_refused(tmp_path):
    db = make_session(tmp_path)
    with pytest.raises(LocalUploadError):
        import_local_media(db, "notes.txt", io.BytesIO(b"x"))
    with pytest.raises(LocalUploadError):
        import_local_media(db, "empty.mp4", io.BytesIO(b""))
    assert db.scalars(select(Video)).all() == []
    assert list((tmp_path / "Local").iterdir()) == []


def test_path_in_filename_cannot_escape_the_media_root(tmp_path):
    db = make_session(tmp_path)
    video, _ = import_local_media(db, "../../evil.mp4", io.BytesIO(b"x"))
    assert (tmp_path / "Local") in __import__("pathlib").Path(video.folder_path).parents


def test_upload_route_answers_json_for_fetch(tmp_path):
    db = make_session(tmp_path)
    request = Request({"type": "http", "headers": [(b"x-requested-with", b"fetch")]})
    upload = type("Upload", (), {"filename": "clip.mp4", "file": io.BytesIO(b"data")})()

    response = videos_routes.upload_local_media(request, upload, db)

    assert response.status_code == 200
    assert b'"video_id"' in response.body

    bad = type("Upload", (), {"filename": "clip.pdf", "file": io.BytesIO(b"data")})()
    refused = videos_routes.upload_local_media(request, bad, db)
    assert refused.status_code == 400
