from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.api import videos as api_videos
from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.deleted_video import DeletedVideo
from back.models.playlist import Playlist, PlaylistItem
from back.models.setting import AppSetting
from back.models.video import TranscriptStatus, Video
from back.services.ingest import metadata_import, scanner


def make_session(media_root):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(AppSetting(key="media_root", value=str(media_root)))
    db.commit()
    return db


def add_fiche(db, folder, yt_video_id="gone123", channel=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video.mp4").write_bytes(b"video bytes")
    video = Video(
        channel=channel,
        yt_video_id=yt_video_id,
        title="Une fiche à supprimer",
        url=f"https://www.youtube.com/watch?v={yt_video_id}",
        media_type="video",
        folder_path=str(folder),
        video_path=str(folder / "video.mp4"),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()
    return video


def test_deleting_a_fiche_removes_its_rows_and_its_folder(tmp_path):
    db = make_session(tmp_path)
    folder = tmp_path / "YouTube" / "Chaîne" / "2026-10-01 - Une fiche"
    video = add_fiche(db, folder)
    playlist = Playlist(title="À voir", source="manual")
    db.add(playlist)
    db.flush()
    db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=1))
    db.commit()

    api_videos.delete_fiche(video.id, db)

    assert db.scalars(select(Video)).all() == []
    assert db.scalars(select(PlaylistItem)).all() == []
    assert db.get(DeletedVideo, "gone123") is not None
    assert not folder.exists()
    assert (tmp_path / "YouTube" / "Chaîne").exists()


def test_deleting_a_fiche_never_removes_a_folder_outside_the_library(tmp_path):
    db = make_session(tmp_path / "library")
    folder = tmp_path / "elsewhere"
    video = add_fiche(db, folder)

    api_videos.delete_fiche(video.id, db)

    assert db.scalars(select(Video)).all() == []
    assert (folder / "video.mp4").exists()


def test_the_fiche_page_offers_the_deletion_and_the_form_goes_back(tmp_path, front_client):
    db = make_session(tmp_path)
    channel = Channel(name="Ma chaîne", url="https://youtube.com/@ma", yt_channel_id="UC1")
    db.add(channel)
    db.commit()
    video = add_fiche(db, tmp_path / "fiche", channel=channel)
    client = front_client(db)

    html = client.get(f"/videos/{video.id}").text
    assert f'action="/videos/{video.id}/delete"' in html
    assert "Supprimer la fiche" in html

    response = client.post(
        f"/videos/{video.id}/delete",
        data={"next": f"/videos?channel_id={channel.id}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos?channel_id={channel.id}&message=")
    assert db.scalars(select(Video)).all() == []

    # Already gone (a second tab), or a `next` naming the deleted page: back to the library.
    response = client.post(
        f"/videos/{video.id}/delete", data={"next": f"/videos/{video.id}"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/videos?message=")


def test_the_scan_does_not_bring_back_a_deleted_fiche(monkeypatch, tmp_path):
    db = make_session(tmp_path)
    channel = Channel(url="https://example.test/channel", name="Auto channel")
    db.add(channel)
    db.commit()
    video = add_fiche(db, tmp_path / "gone", channel=channel)
    api_videos.delete_fiche(video.id, db)

    def fake_list_channel_entries(channel, page=1, page_size=25, section="videos"):
        if page == 1:
            return [{"id": "gone123", "title": "Supprimée", "url": "https://example.test/gone"}]
        raise AssertionError("the deleted fiche stops the scan like a known one")

    def fail_import(*args, **kwargs):
        raise AssertionError("a deleted fiche must not be imported again")

    monkeypatch.setattr(scanner, "list_channel_entries", fake_list_channel_entries)
    monkeypatch.setattr(scanner, "import_video_metadata", fail_import)
    monkeypatch.setattr(metadata_import, "extract_video_info", fail_import)

    assert scanner.scan_channel(db, channel, max_pages=3, mark_new=True) == 0
