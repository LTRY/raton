"""`/api` actions on a fiche and `GET /api/jobs/{id}`."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import video_actions
from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.job import DownloadJob
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.services.youtube import sponsor_segments


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
def video(db, tmp_path):
    video = Video(
        yt_video_id="abc",
        title="Fiche",
        url="https://youtube.com/watch?v=abc",
        folder_path=str(tmp_path),
        is_new=True,
    )
    db.add(video)
    db.commit()
    return video


def test_open_takes_the_fiche_out_of_nouveautes(client, db, video):
    response = client.post(f"/api/videos/{video.id}/open")

    assert response.status_code == 200
    assert response.json()["is_new"] is False
    db.refresh(video)
    assert video.is_new is False


def test_list_state_sets_and_clears_the_choice(client, video):
    hidden = client.put(f"/api/videos/{video.id}/list-state", json={"state": "hidden"})
    cleared = client.put(f"/api/videos/{video.id}/list-state", json={"state": "clear"})
    refused = client.put(f"/api/videos/{video.id}/list-state", json={"state": "bogus"})

    assert hidden.json()["list_state"] == "hidden"
    assert cleared.json()["list_state"] is None
    assert refused.status_code == 400
    assert refused.json() == {"detail": "État de liste inconnu."}


def test_categories_and_comment_are_stored_normalized(client, video):
    categories = client.put(
        f"/api/videos/{video.id}/categories", json={"categories": ["Cuisine", " cuisine ", "Maker"]}
    )
    comment = client.put(f"/api/videos/{video.id}/comment", json={"comment": "  À revoir  "})
    emptied = client.put(f"/api/videos/{video.id}/comment", json={"comment": "   "})

    assert categories.json()["categories"] == ["cuisine", "maker"]
    assert comment.json()["comment"] == "À revoir"
    assert emptied.json()["comment"] is None


def test_activity_records_playback_and_marks_vu_when_complete(client, db, video):
    response = client.post(
        f"/api/videos/{video.id}/activity",
        json={"media_type": "audio", "position_seconds": 99, "duration_seconds": 100},
    )
    refused = client.post(f"/api/videos/{video.id}/activity", json={"media_type": "vhs"})

    assert response.status_code == 200
    assert response.json()["watched_at"] is not None
    assert db.query(DownloadJob).filter_by(status="played", video_id=video.id).count() == 1
    assert refused.status_code == 400
    assert refused.json() == {"detail": "Type de média invalide"}


def test_media_download_queues_a_job_and_runs_it_in_the_background(client, db, video, monkeypatch):
    calls = []
    monkeypatch.setattr(video_actions, "run_media_download_job", lambda *args: calls.append(args))

    response = client.post(
        f"/api/videos/{video.id}/media/audio/download", json={"video_quality": "720"}
    )
    default = client.post(f"/api/videos/{video.id}/media/video/download")
    bad_format = client.post(f"/api/videos/{video.id}/media/subtitles/download")
    bad_quality = client.post(
        f"/api/videos/{video.id}/media/video/download", json={"video_quality": "9000"}
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "queued"
    assert response.json()["status_url"] == f"/api/jobs/{job_id}"
    assert calls == [
        (job_id, video.url, "audio", "720"),
        (default.json()["job_id"], video.url, "video", "1080"),
    ]
    assert bad_format.status_code == 400
    assert bad_format.json() == {"detail": "Le format doit être vidéo ou audio."}
    assert bad_quality.status_code == 400


def test_job_status_is_polled_until_done(client, db, video, monkeypatch):
    monkeypatch.setattr(video_actions, "run_transcript_retry_job", lambda *args: None)
    queued = client.post(f"/api/videos/{video.id}/transcript/download").json()

    status = client.get(queued["status_url"]).json()
    job = db.get(DownloadJob, queued["job_id"])
    job.status = "downloaded"
    db.commit()
    done = client.get(queued["status_url"]).json()

    assert status == {
        "id": queued["job_id"],
        "status": "queued",
        "message": "Récupération du transcript en file d'attente.",
        "video_id": video.id,
        "done": False,
    }
    assert done["done"] is True
    assert client.get("/api/jobs/999").json() == {"detail": "Job introuvable"}


def test_media_delete_refuses_an_unknown_format(client, video):
    response = client.delete(f"/api/videos/{video.id}/media/subtitles")

    assert response.status_code == 400


def test_sponsor_segments_fetch_stores_and_returns_the_segments(client, db, video, monkeypatch):
    monkeypatch.setattr(
        sponsor_segments,
        "fetch_sponsorblock_segments",
        lambda yt_video_id, categories: [
            {"category": "sponsor", "start_seconds": 10.0, "end_seconds": 40.0}
        ],
    )

    response = client.post(f"/api/videos/{video.id}/sponsor-segments/fetch")

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "skip_enabled": True,
        "segments": [{"start": 10.0, "end": 40.0}],
    }
    assert db.query(VideoSponsorSegment).count() == 1


def test_sponsor_segments_fetch_reports_a_sponsorblock_failure(client, video, monkeypatch):
    def fail(*args):
        raise RuntimeError("timeout")

    monkeypatch.setattr(sponsor_segments, "fetch_sponsorblock_segments", fail)

    response = client.post(f"/api/videos/{video.id}/sponsor-segments/fetch")

    assert response.status_code == 502
    assert response.json() == {"detail": "Recherche SponsorBlock impossible : timeout"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/videos/999/open"),
        ("put", "/api/videos/999/list-state"),
        ("post", "/api/videos/999/media/audio/download"),
        ("delete", "/api/videos/999/media/audio"),
        ("post", "/api/videos/999/transcript/download"),
        ("post", "/api/videos/999/sponsor-segments/fetch"),
    ],
)
def test_actions_refuse_an_unknown_fiche(client, db, method, path):
    kwargs = {"json": {"state": "hidden"}} if method == "put" else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Vidéo introuvable"}
