import asyncio
import json
import pathlib
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from back import main
from back.api import channels as api_channels
from back.api import imports as api_imports
from back.api import llm as llm_api
from back.api import media as api_media
from back.api import settings as api_settings
from back.api import videos as api_videos
from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.llm_job import LlmJob
from back.models.setting import AppSetting
from back.models.video import TranscriptStatus, Video
from back.models.video_sponsor_segment import VideoSponsorSegment
from back.schemas.llm import QuestionCreate
from back.schemas.settings import SettingsUpdate
from back.services.channels import listing as channel_listing
from back.services.channels import manage as channel_manage
from back.services.common import search
from back.services.common.settings import (
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
)
from back.services.ingest.identity import channel_values_from_info
from back.services.jobs import backfills, download_requests, downloads, llm_jobs
from back.services.jobs.scheduler import record_scan_result
from back.services.llm.provider import CompletionFailed, CompletionResult, UsageTally
from back.services.videos import editing as videos_editing
from back.services.videos import list_state as videos_list_state
from back.services.videos import playback as videos_playback
from back.services.videos.filters import video_badges
from back.services.youtube import channel_info, sponsor_segments
from back.services.youtube.channel_info import ChannelNotFoundError, resolve_channel_url
from front import cards as front_cards
from front import formatting
from front import main as front_main
from front.records import record
from front.routes import videos as front_videos_routes
from tests.site import site_client


def make_session():
    # StaticPool + check_same_thread: the back serves the front's calls from another thread.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture(autouse=True)
def reset_back_db():
    yield
    main.app.dependency_overrides.pop(get_db, None)


def site(db, **kwargs):
    """The site (front + back in-process) with the back serving `db`."""
    main.app.dependency_overrides[get_db] = lambda: db
    return site_client(**kwargs)


@pytest.fixture
def no_profile_backfill(monkeypatch):
    """Adding a channel queues the profile backfill, which opens its own (Postgres) session."""
    return record_calls(monkeypatch, api_channels, "run_channel_profile_backfill_job")


def record_calls(monkeypatch, target, name):
    """Replaces a background job with a recorder of its arguments."""
    calls = []
    monkeypatch.setattr(target, name, lambda *args: calls.append(args))
    return calls


def post_form(db, url, data=None, **kwargs):
    """A no-JS form posted to the front; the redirect is returned, not followed."""
    return site(db).post(url, data=data or {}, follow_redirects=False, **kwargs)


def add_video(db):
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    video = Video(
        channel=channel,
        yt_video_id="abc123",
        title="Une vidéo à lire localement",
        url="https://youtube.com/watch?v=abc123",
        media_type="video",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        folder_path="/media/video",
        video_path="/media/video/video.mp4",
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=5 * 1024 * 1024,
    )
    db.add(video)
    db.commit()
    return video


def test_video_card_has_local_title_without_youtube_or_transcript_link():
    db = make_session()
    channel = Channel(url="https://example.test/locale", name="Chaîne locale")
    video = Video(
        channel=channel,
        yt_video_id="abc",
        title="Titre local",
        url="https://youtube.com/watch?v=abc",
        media_type="video",
        folder_path="/media",
        transcript_path="/media/transcript.txt",
        transcript_status=TranscriptStatus.downloaded,
        video_path="/media/video.mp4",
        thumbnail_path="/media/thumbnail.webp",
        metadata_path="/media/metadata.json",
        rating=0,
        file_size_bytes=0,
        view_count=12345,
        duration_seconds=123,
    )
    db.add(video)
    db.commit()

    rendered = site(db).get("/videos").text

    card = rendered[rendered.index('<article class="video-row"') :]
    assert (
        f'<a class="video-title" href="/videos/{video.id}?next=/videos" title="Titre local">Titre local</a>'
        in card
    )
    assert (
        f'<a class="video-meta-link" href="/videos?channel_id={channel.id}">Chaîne locale</a>'
        in card
    )
    assert "Téléchargement manuel" not in card
    assert card.index(
        f'<a class="video-title" href="/videos/{video.id}?next=/videos"'
    ) < card.index(f'action="/videos/{video.id}/rating"')
    assert card.index('<p class="video-meta">') < card.index(f'action="/videos/{video.id}/rating"')
    assert "video-row-rating" in card
    assert 'class="rating-control rating-control-minimal video-row-rating rating-tier-0"' in card
    assert "rating-star-empty" in card
    assert '<span aria-hidden="true">☆</span>' not in card
    assert '<span aria-hidden="true">★</span>' in card
    assert "Voir les détails" not in card
    assert "youtube.com" not in card.lower()
    assert ">YouTube<" not in card
    assert f'href="/videos/{video.id}/transcript"' not in card
    assert 'class="asset-label asset-label-video">Vidéo</span>' not in card
    assert 'class="asset-label asset-label-metadata">Métadonnées</span>' not in card
    assert 'class="asset-label asset-label-transcript">Transcript</span>' not in card
    assert 'class="asset-label asset-label-rating">★ Notées</span>' in rendered
    assert 'class="video-title-preview"' not in card
    assert "data-video-format-actions" not in card
    assert "format-toggle" not in card
    assert 'class="video-thumbnail-popover"' not in card
    assert f'src="/api/videos/{video.id}/thumbnail"' not in card
    assert "Transcript :" not in card


def test_video_thumbnail_serves_file_from_video_folder(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    thumbnail = folder / "thumbnail.webp"
    thumbnail.write_bytes(b"thumbnail")
    video = Video(
        yt_video_id="thumb123",
        title="Vidéo avec vignette",
        url="https://youtube.com/watch?v=thumb123",
        folder_path=str(folder),
        thumbnail_path=str(thumbnail),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    response = api_media.video_thumbnail(video.id, db)

    assert response.path == thumbnail
    assert response.headers["cache-control"] == "public, max-age=86400"


def test_video_thumbnail_rejects_file_outside_video_folder(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    thumbnail = tmp_path / "outside.webp"
    thumbnail.write_bytes(b"thumbnail")
    video = Video(
        yt_video_id="outside123",
        title="Vidéo avec chemin incorrect",
        url="https://youtube.com/watch?v=outside123",
        folder_path=str(folder),
        thumbnail_path=str(thumbnail),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        api_media.video_thumbnail(video.id, db)

    assert exc_info.value.status_code == 404


def test_video_detail_page_renders_internal_page_without_youtube_action(monkeypatch):
    db = make_session()
    video = add_video(db)
    video.thumbnail_path = "/media/video/thumbnail.webp"
    video.comment = "À revoir pour le passage sur les exemples."
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert "Une vidéo à lire localement" in rendered
    assert 'href="/videos"' in rendered
    assert "Voir la source sur YouTube" not in rendered
    assert ">YouTube<" not in rendered
    assert 'class="video-detail-thumbnail"' not in rendered
    assert 'class="video-player-panel"' in rendered
    assert f'poster="/api/videos/{video.id}/thumbnail"' in rendered
    assert f'data-resume-key="raton:media-position:{video.id}:video"' in rendered
    assert f'<source src="/api/videos/{video.id}/video">' in rendered
    assert "Commentaire" in rendered
    assert f'action="/videos/{video.id}/comment"' in rendered
    assert "À revoir pour le passage sur les exemples." in rendered
    assert "data-video-format-actions" in rendered
    assert 'data-allow-delete="true"' in rendered
    assert 'title="Télécharger l’audio"' in rendered
    assert 'title="Cliquer pour supprimer la vidéo"' in rendered
    assert "Supprimer la vidéo ?" in rendered
    assert "Supprimer l’audio ?" not in rendered


def test_video_comment_form_updates_comment():
    db = make_session()
    video = add_video(db)

    response = post_form(
        db,
        f"/videos/{video.id}/comment",
        {"comment": "  Note perso\nsur deux lignes  ", "next": "/videos/1#notes"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/videos/1#notes"
    assert video.comment == "Note perso\nsur deux lignes"


def test_video_comment_form_clears_blank_comment():
    db = make_session()
    video = add_video(db)
    video.comment = "Ancienne note"
    db.commit()

    post_form(db, f"/videos/{video.id}/comment", {"comment": "   ", "next": "/videos/1#notes"})

    assert video.comment is None


def test_video_detail_page_embeds_transcript_and_discussion(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Bonjour depuis le transcript.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.video_path = str(folder / "video.mp4")
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert 'id="transcript"' in rendered
    assert 'id="transcript-content"' in rendered
    assert "Bonjour depuis le transcript." in rendered
    assert 'id="discussion"' in rendered
    assert "Pose une question sur le transcript." not in rendered
    assert f'"chatUrl": "/api/videos/{video.id}/chat"' in rendered
    assert f'action="/videos/{video.id}/transcript/clean"' not in rendered
    assert f'action="/videos/{video.id}/transcript/revert"' not in rendered
    assert 'data-tab="cleaned"' not in rendered
    assert f'action="/videos/{video.id}/transcript/generate"' in rendered
    # Bouton robot : icone seule, libelle porte par aria-label, infobulle au survol.
    assert 'class="ai-generate-button"' in rendered
    assert 'aria-label="Générer notes, résumé"' in rendered
    assert 'id="ai-generate-tooltip"' in rendered
    assert "Analyse de pertinence" not in rendered
    assert 'name="include_image"' not in rendered
    assert f'href="/videos/{video.id}/transcript"' not in rendered


def test_video_asset_labels_includes_notes_only_when_notes_file_exists(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Bonjour depuis le transcript.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    labels_without_notes = front_cards.badge_labels(video_badges(video))
    assert not any(label["kind"] == "notes" for label in labels_without_notes)

    (folder / "transcript.notes.txt").write_text("- Fait 1", encoding="utf-8")

    labels_with_notes = front_cards.badge_labels(video_badges(video))
    assert {"text": "Notes", "kind": "notes"} in labels_with_notes


def test_video_detail_page_shows_notes_label_when_notes_generated(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Bonjour depuis le transcript.", encoding="utf-8")
    (folder / "transcript.notes.txt").write_text("- Fait 1", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.video_path = str(folder / "video.mp4")
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert '<span class="asset-label asset-label-notes">Notes</span>' in rendered


def test_videos_page_hides_labels_on_card(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Bonjour depuis le transcript.", encoding="utf-8")
    (folder / "transcript.notes.txt").write_text("- Fait 1", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get("/videos")
    rendered = response.text

    card = rendered[rendered.index('<article class="video-row') :]
    card = card[: card.index("</article>")]
    assert 'class="asset-label' not in card
    assert 'class="category-label' not in card


def test_failed_llm_job_keeps_the_cost_of_a_truncated_response(monkeypatch):
    db = make_session()
    job = llm_jobs.enqueue_llm_job(db, kind="chat", provider="anthropic", video_id=None, prompt="p")

    class FakeProvider:
        def complete(self, messages, on_text=None, system=None):
            tally = UsageTally("claude-haiku-5-5")
            tally.add(SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000))
            raise CompletionFailed("La réponse a été tronquée", tally)

    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfills, "SessionLocal", lambda: db)

    llm_jobs.run_llm_job(job.id)

    failed = db.get(LlmJob, job.id)
    assert failed.status == "failed"
    assert failed.model == "claude-haiku-5-5"
    assert failed.output_tokens == 1_000_000
    assert failed.cost_usd == pytest.approx(
        0.50 + 2.50
    )  # prompt over 100K tokens -> long-prompt tier


def test_fetch_video_sponsorblock_segments_inserts_rows(monkeypatch, tmp_path):
    db = make_session()
    video = add_video(db)
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,intro"))
    db.commit()

    monkeypatch.setattr(
        sponsor_segments,
        "fetch_sponsorblock_segments",
        lambda yt_video_id, categories: [
            {"category": "sponsor", "start_seconds": 10.0, "end_seconds": 20.0}
        ],
    )

    response = post_form(db, f"/videos/{video.id}/sponsors/fetch")

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/videos/{video.id}?message=1+segment+trouv%C3%A9.#segments-sponsors"
    )
    rows = list(
        db.scalars(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
    )
    assert len(rows) == 1
    assert rows[0].category == "sponsor"
    assert rows[0].source == "sponsorblock"


def test_fetch_video_sponsorblock_segments_reports_error_without_writing(monkeypatch):
    db = make_session()
    video = add_video(db)

    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sponsor_segments, "fetch_sponsorblock_segments", fail)

    response = post_form(db, f"/videos/{video.id}/sponsors/fetch")

    assert response.status_code == 303
    assert "level=error" in response.headers["location"]
    assert response.headers["location"].endswith("#segments-sponsors")
    assert (
        db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
        is None
    )


def test_sponsors_detect_route_is_gone():
    assert not hasattr(front_videos_routes, "detect_video_sponsor_segments")
    for app in (main.app, front_main.app):
        assert not any("sponsors/detect" in getattr(route, "path", "") for route in app.routes)


def test_api_sponsor_segments_returns_normalized_payload():
    db = make_session()
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,intro"))
    db.commit()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=30.0,
            end_seconds=60.0,
            source="sponsorblock",
        )
    )
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="intro",
            start_seconds=0.0,
            end_seconds=8.0,
            source="sponsorblock",
        )
    )
    db.commit()

    payload = api_videos.get_video_sponsor_segments(video.id, db).model_dump()

    assert payload["skip_enabled"] is True
    assert payload["segments"] == [{"start": 0.0, "end": 8.0}, {"start": 30.0, "end": 60.0}]


def test_api_sponsor_segments_filters_out_unchecked_categories():
    db = make_session()
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor"))
    db.commit()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=30.0,
            end_seconds=60.0,
            source="sponsorblock",
        )
    )
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="intro",
            start_seconds=0.0,
            end_seconds=8.0,
            source="sponsorblock",
        )
    )
    db.commit()

    payload = api_videos.get_video_sponsor_segments(video.id, db).model_dump()

    assert payload["segments"] == [{"start": 30.0, "end": 60.0}]


def test_api_sponsor_segments_reports_skip_disabled():
    db = make_session()
    db.add(AppSetting(key="sponsor_skip_enabled", value="false"))
    db.commit()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=30.0,
            end_seconds=60.0,
            source="sponsorblock",
        )
    )
    db.commit()

    payload = api_videos.get_video_sponsor_segments(video.id, db).model_dump()

    # La route renvoie toujours les segments : c'est le client qui décide de les
    # armer ou non à partir de `skip_enabled` (front/static/js/app.js).
    assert payload["skip_enabled"] is False
    assert payload["segments"] == [{"start": 30.0, "end": 60.0}]


def test_api_sponsor_segments_raises_404_for_unknown_video():
    db = make_session()

    with pytest.raises(HTTPException) as excinfo:
        api_videos.get_video_sponsor_segments(999, db)

    assert excinfo.value.status_code == 404


GENERATION_RESULT_TEXT = (
    "# Notes\n## Faits\n- Fait 1\n- Fait 2\n\n## Dates\nAucun élément identifié.\n\n"
    "## Lieux\nAucun élément identifié.\n\n## Acteurs\nAucun élément identifié.\n\n"
    "## Concepts\nAucun élément identifié.\n\n## Relations causales\nAucun élément identifié.\n\n"
    "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
    "## Questions suggérées\n- Question A ?\n- Question B ?\n\n"
)


def test_generate_job_exposes_the_summary_while_it_streams(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()
    video_id = video.id
    job = LlmJob(
        kind="generate", provider="anthropic", video_id=video_id, prompt="...", status="queued"
    )
    db.add(job)
    db.commit()
    job_id = job.id

    assert llm_api.get_llm_job(job_id, BackgroundTasks(), db).partial_short_summary is None

    streamed = "# Résumé\n## Résumé court\nLigne 1."
    polled = []

    class FakeProvider:
        def complete(self, messages, on_text=None, system=None):
            on_text(streamed)
            polled.append(llm_api.get_llm_job(job_id, BackgroundTasks(), db))
            return CompletionResult(
                text=GENERATION_RESULT_TEXT,
                model="claude-haiku-4-5",
                input_tokens=200,
                output_tokens=80,
            )

    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfills, "SessionLocal", lambda: db)
    monkeypatch.setattr(llm_jobs, "PARTIAL_RESULT_INTERVAL_SECONDS", 0)

    llm_jobs.run_llm_job(job_id)

    assert [(job.status, job.partial_short_summary) for job in polled] == [("pending", "Ligne 1.")]
    assert db.get(LlmJob, job_id).result == GENERATION_RESULT_TEXT


def test_transcript_job_status_schedules_notes_indexing_once_and_only_once(tmp_path, monkeypatch):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    job = LlmJob(
        kind="generate",
        provider="anthropic",
        video_id=video.id,
        prompt="...",
        status="done",
        result=GENERATION_RESULT_TEXT,
    )
    db.add(job)
    db.commit()

    scheduled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    status = llm_api.get_llm_job(job.id, background_tasks, db)
    assert status.status == "done"
    assert "- Fait 1\n- Fait 2" in status.documents.notes
    assert len(scheduled) == 1
    fn, args, kwargs = scheduled[0]
    assert fn is llm_api.run_notes_indexing_job
    assert args[0] == video.id
    assert "- Fait 1\n- Fait 2" in args[1]
    assert kwargs == {}

    # Idempotent replay ("applied") must not reschedule indexing a second time.
    scheduled.clear()
    llm_api.get_llm_job(job.id, background_tasks, db)
    assert scheduled == []


def test_video_detail_page_hides_summary_tab_and_blurb_when_absent(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert "Générer notes, résumé" in rendered
    assert f'action="/videos/{video.id}/transcript/generate"' in rendered
    assert 'data-tab="summary"' not in rendered
    assert '<p id="video-short-summary" class="video-short-summary" hidden></p>' in rendered


def test_video_detail_page_shows_the_short_summary_blurb_when_present(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    summary_short = folder / "transcript.summary_short.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    summary_short.write_text("Résumé court existant.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert (
        '<p id="video-short-summary" class="video-short-summary" >Résumé court existant.</p>'
        in rendered
    )
    assert 'data-tab="summary"' not in rendered


def test_video_detail_page_opens_with_no_active_tab(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert "transcript-tab active" not in rendered
    assert not re.search(r'class="transcript-tab"[^>]*aria-selected="true"', rendered)
    assert '<div data-tab-panel="text" hidden>' in rendered
    for panel in ("vtt", "personal-notes", "info", "segments"):
        assert re.search(rf'data-tab-panel="{panel}" hidden>', rendered), panel


def test_video_detail_page_tab_order_starts_with_info_segments_raw(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    tab_order = re.findall(r'class="transcript-tab[^"]*" data-tab="([a-z-]+)"', rendered)
    assert tab_order[:3] == ["info", "segments", "raw"]
    assert tab_order[3:] == ["notes", "vtt", "personal-notes"]


def test_video_detail_page_has_personal_notes_tab_and_no_analysis_tab(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert 'data-tab="personal-notes"' in rendered
    assert 'data-tab="analysis"' not in rendered
    assert 'data-tab-panel="personal-notes"' in rendered
    assert 'data-tab-panel="analysis"' not in rendered
    assert f'action="/videos/{video.id}/comment"' in rendered


def test_video_detail_page_renders_sponsor_segments(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    subtitle = folder / "video.fr.vtt"
    subtitle.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nBonjour\n", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.subtitle_path = str(subtitle)
    db.commit()
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=42.0,
            end_seconds=105.0,
            source="sponsorblock",
        )
    )
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="intro",
            start_seconds=0.0,
            end_seconds=8.0,
            source="sponsorblock",
        )
    )
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert "Segments détectés" in rendered
    assert "Rechercher les segments sponsors" in rendered
    assert 'data-seek-time="42.0"' in rendered
    assert "Sponsor" in rendered  # French label for category "sponsor"


def test_video_detail_page_renders_segments_tab_and_skip_payload():
    db = make_session()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=42.0,
            end_seconds=105.0,
            source="sponsorblock",
        )
    )
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert 'data-tab="segments"' in rendered
    assert 'data-tab-panel="segments"' in rendered
    assert "data-sponsor-skip" in rendered
    assert '"start": 42.0' in rendered
    assert '"end": 105.0' in rendered
    # La liste visible et le payload de saut viennent des mêmes lignes : la
    # requête ne doit être consommée qu'une fois (voir le `list(...)` de l'étape 3).
    assert 'data-seek-time="42.0"' in rendered


def test_video_detail_page_skip_payload_disabled_by_setting():
    db = make_session()
    db.add(AppSetting(key="sponsor_skip_enabled", value="false"))
    db.commit()
    video = add_video(db)
    db.add(
        VideoSponsorSegment(
            video_id=video.id,
            category="sponsor",
            start_seconds=42.0,
            end_seconds=105.0,
            source="sponsorblock",
        )
    )
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert '"enabled": false' in rendered


def test_video_detail_page_shows_segments_tab_without_any_segment():
    db = make_session()
    video = add_video(db)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    # L'onglet est le seul point d'entrée du bouton de recherche : il doit rester
    # atteignable même sans segment stocké.
    assert 'data-tab="segments"' in rendered
    assert "Rechercher les segments sponsors" in rendered


def test_transcript_job_status_pending_while_queued(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()
    job = LlmJob(
        kind="generate",
        provider="anthropic",
        video_id=video.id,
        prompt="x",
        status="queued",
    )
    db.add(job)
    db.commit()

    status = llm_api.get_llm_job(job.id, BackgroundTasks(), db)

    assert status.status == "pending"
    assert status.documents is None


def test_transcript_job_status_reports_failure(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()
    job = LlmJob(
        kind="generate",
        provider="anthropic",
        video_id=video.id,
        prompt="x",
        status="failed",
        error="API indisponible.",
    )
    db.add(job)
    db.commit()

    status = llm_api.get_llm_job(job.id, BackgroundTasks(), db)

    assert status.status == "failed"
    assert "API indisponible." in status.message


def test_chat_enqueues_job_and_resolving_appends_history(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Contenu du transcript.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    queued = llm_api.ask_about_video(
        video.id, QuestionCreate(question="Question ?"), BackgroundTasks(), db
    )

    job = db.get(LlmJob, queued.job_id)
    assert job.kind == "chat"
    assert job.provider == "anthropic"
    assert job.question == "Question ?"
    assert "Question ?" in json.loads(job.prompt)["messages"][-1]["content"]

    job.status = "done"
    job.result = "Réponse du LLM."
    db.commit()

    resolved = llm_api.get_llm_job(job.id, BackgroundTasks(), db)

    assert resolved.status == "done"
    assert [message.model_dump() for message in resolved.chat_messages] == [
        {"role": "user", "content": "Question ?"},
        {"role": "assistant", "content": "Réponse du LLM."},
    ]
    assert (folder / "transcript.chat.json").exists()

    # Re-polling must not duplicate the appended messages.
    second_resolved = llm_api.get_llm_job(job.id, BackgroundTasks(), db)
    assert len(second_resolved.chat_messages) == 2


def test_video_chat_queues_job_and_resolves_after_background_task(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Contenu du transcript.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()

    class FakeProvider:
        def complete(self, messages, on_text=None, system=None):
            assert "Question ?" in messages[-1]["content"]
            return CompletionResult(
                text="Réponse à Question ?",
                model="claude-haiku-4-5",
                input_tokens=30,
                output_tokens=10,
            )

    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfills, "SessionLocal", lambda: db)

    scheduled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    job_id = llm_api.ask_about_video(
        video.id, QuestionCreate(question="Question ?"), background_tasks, db
    ).job_id
    assert scheduled == [(llm_jobs.run_llm_job, (job_id,), {})]

    # Simulate the background task the request scheduled.
    llm_jobs.run_llm_job(job_id)

    resolved = llm_api.get_llm_job(job_id, BackgroundTasks(), db)

    assert resolved.status == "done"
    assert [message.model_dump() for message in resolved.chat_messages] == [
        {"role": "user", "content": "Question ?"},
        {"role": "assistant", "content": "Réponse à Question ?"},
    ]
    assert (folder / "transcript.chat.json").exists()
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "prompt"))
    assert job is not None
    assert job.video_id == video.id
    assert job.channel_id == video.channel_id
    assert "Prompt envoyé sur Une vidéo à lire localement: Question ?" in job.message


def test_clearing_the_video_chat_deletes_its_file(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    transcript.write_text("Contenu du transcript.", encoding="utf-8")
    (folder / "transcript.chat.json").write_text(
        json.dumps([{"role": "user", "content": "Ancienne question"}]),
        encoding="utf-8",
    )
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()
    llm_api.clear_video_chat(video.id, db)

    assert not (folder / "transcript.chat.json").exists()


def test_video_transcript_page_redirects_to_video_detail_anchor():
    db = make_session()
    video = add_video(db)

    response = site(db).get(f"/videos/{video.id}/transcript?message=ok", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/videos/{video.id}?message=ok#transcript"


def test_audio_only_video_detail_renders_mini_player_trigger(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "audio"
    folder.mkdir()
    audio = folder / "episode.mp3"
    audio.write_bytes(b"audio bytes")
    video = Video(
        yt_video_id="audio123",
        title="Un audio local",
        url="https://youtube.com/watch?v=audio123",
        media_type="audio",
        folder_path=str(folder),
        audio_path=str(audio),
        thumbnail_path=str(folder / "thumbnail.webp"),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert 'class="audio-player-panel audio-player-panel-trigger"' in rendered
    assert 'class="video-player-panel media-thumbnail-panel"' in rendered
    assert 'class="audio-player-thumbnail"' in rendered
    assert f'src="/api/videos/{video.id}/thumbnail"' in rendered
    assert "data-play-track" in rendered
    assert f'data-track-id="{video.id}"' in rendered
    assert f'data-track-src="/api/videos/{video.id}/audio"' in rendered
    assert f'data-track-thumb="/api/videos/{video.id}/thumbnail"' in rendered
    assert f'data-track-resume-key="raton:media-position:{video.id}:audio"' in rendered
    assert f'data-track-activity-url="/api/videos/{video.id}/activity"' in rendered
    assert f'data-track-detail-url="/videos/{video.id}"' in rendered
    assert '<audio controls preload="metadata" src="/api/videos/' not in rendered
    assert "Supprimer l’audio ?" in rendered
    assert "Supprimer la vidéo ?" not in rendered


def test_audio_and_video_detail_keeps_native_audio_player(monkeypatch, tmp_path):
    db = make_session()
    folder = tmp_path / "combined"
    folder.mkdir()
    audio = folder / "episode.mp3"
    audio.write_bytes(b"audio bytes")
    video = Video(
        yt_video_id="combined123",
        title="Video et audio combines",
        url="https://youtube.com/watch?v=combined123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(folder / "episode.mp4"),
        audio_path=str(audio),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert response.status_code == 200
    assert 'class="audio-player-panel"' in rendered
    assert 'class="audio-player-panel audio-player-panel-trigger"' not in rendered
    assert '<audio controls preload="metadata" src="/api/videos/' in rendered
    assert f'src="/api/videos/{video.id}/audio"' in rendered
    assert f'data-resume-key="raton:media-position:{video.id}:audio"' in rendered
    assert "data-play-track" not in rendered


def test_delete_video_media_removes_file_and_keeps_audio(tmp_path):
    db = make_session()
    folder = tmp_path / "media"
    folder.mkdir()
    video_file = folder / "video.mp4"
    audio_file = folder / "audio.mp3"
    video_file.write_bytes(b"video bytes")
    audio_file.write_bytes(b"audio bytes")
    video = Video(
        yt_video_id="deletevideo123",
        title="Vidéo avec deux fichiers",
        url="https://youtube.com/watch?v=deletevideo123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(video_file),
        audio_path=str(audio_file),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    response = post_form(
        db, f"/videos/{video.id}/media/video/delete", {"next": f"/videos/{video.id}"}
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos/{video.id}?")
    assert not video_file.exists()
    assert audio_file.exists()
    assert video.video_path is None
    assert video.audio_path == str(audio_file)
    assert video.media_type == "audio"
    assert video.file_size_bytes == len(b"audio bytes")


def test_api_delete_media_removes_the_file(tmp_path):
    db = make_session()
    folder = tmp_path / "media"
    folder.mkdir()
    video_file = folder / "video.mp4"
    video_file.write_bytes(b"video bytes")
    video = Video(
        yt_video_id="deletefetch123",
        title="Vidéo à supprimer en AJAX",
        url="https://youtube.com/watch?v=deletefetch123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(video_file),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    api_videos.delete_media(video.id, "video", db)

    assert not video_file.exists()
    assert video.video_path is None


def test_api_delete_media_refuses_a_missing_file(tmp_path):
    db = make_session()
    folder = tmp_path / "media"
    folder.mkdir()
    video = Video(
        yt_video_id="deletefetcherr123",
        title="Vidéo déjà absente",
        url="https://youtube.com/watch?v=deletefetcherr123",
        media_type="metadata",
        folder_path=str(folder),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    with pytest.raises(HTTPException) as refused:
        api_videos.delete_media(video.id, "video", db)

    assert refused.value.status_code == 400


def test_delete_audio_media_removes_file_and_keeps_video(tmp_path):
    db = make_session()
    folder = tmp_path / "media"
    folder.mkdir()
    video_file = folder / "video.mp4"
    audio_file = folder / "audio.mp3"
    video_file.write_bytes(b"video bytes")
    audio_file.write_bytes(b"audio bytes")
    video = Video(
        yt_video_id="deleteaudio123",
        title="Vidéo avec audio",
        url="https://youtube.com/watch?v=deleteaudio123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(video_file),
        audio_path=str(audio_file),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    response = post_form(
        db, f"/videos/{video.id}/media/audio/delete", {"next": f"/videos/{video.id}"}
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos/{video.id}?")
    assert video_file.exists()
    assert not audio_file.exists()
    assert video.video_path == str(video_file)
    assert video.audio_path is None
    assert video.media_type == "video"
    assert video.file_size_bytes == len(b"video bytes")


def test_download_video_media_form_queues_job_and_redirects(monkeypatch):
    db = make_session()
    video = add_video(db)
    calls = record_calls(monkeypatch, api_videos, "run_media_download_job")

    response = post_form(db, f"/videos/{video.id}/media/audio/download")

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos/{video.id}?message=")
    assert (job.status, job.video_id) == ("queued", video.id)
    assert calls == [(job.id, video.url, "audio", "1080")]


def test_download_video_media_form_returns_to_an_internal_next_only(monkeypatch):
    db = make_session()
    video = add_video(db)
    record_calls(monkeypatch, api_videos, "run_media_download_job")
    url = f"/videos/{video.id}/media/video/download"

    inside = post_form(
        db, url, {"video_quality": "1080", "next": "/videos?channel_id=1&section=shorts"}
    )
    outside = post_form(db, url, {"video_quality": "1080", "next": "https://evil.example/"})

    assert inside.headers["location"].startswith("/videos?channel_id=1&section=shorts&message=")
    assert outside.headers["location"].startswith(f"/videos/{video.id}?message=")


def test_download_video_media_rejects_invalid_format(monkeypatch):
    db = make_session()
    video = add_video(db)
    calls = record_calls(monkeypatch, api_videos, "run_media_download_job")

    response = post_form(db, f"/videos/{video.id}/media/subtitles/download")

    assert response.status_code == 400
    assert calls == []
    assert db.scalar(select(DownloadJob)) is None


def test_run_transcript_retry_job_marks_job_downloaded_on_success(monkeypatch):
    db = make_session()
    video = add_video(db)
    job = DownloadJob(video_id=video.id, status="queued", message="En file d'attente.")
    db.add(job)
    db.commit()

    def fake_retry_transcript_download(session, target_video, languages=None):
        target_video.transcript_path = "/media/video/transcript.txt"
        target_video.transcript_status = TranscriptStatus.downloaded
        return target_video

    monkeypatch.setattr(downloads, "retry_transcript_download", fake_retry_transcript_download)
    monkeypatch.setattr(downloads, "SessionLocal", lambda: db)

    downloads.run_transcript_retry_job(job.id, video.id)

    completed_job = db.get(DownloadJob, job.id)
    assert completed_job.status == "downloaded"
    assert completed_job.video_id == video.id


def test_run_transcript_retry_job_marks_job_failed_when_no_subtitles_found(monkeypatch):
    db = make_session()
    video = add_video(db)
    job = DownloadJob(video_id=video.id, status="queued", message="En file d'attente.")
    db.add(job)
    db.commit()

    def fake_retry_transcript_download(session, target_video, languages=None):
        raise ValueError("Aucun sous-titre disponible (FR ou EN) pour cette vidéo.")

    monkeypatch.setattr(downloads, "retry_transcript_download", fake_retry_transcript_download)
    monkeypatch.setattr(downloads, "SessionLocal", lambda: db)

    downloads.run_transcript_retry_job(job.id, video.id)

    completed_job = db.get(DownloadJob, job.id)
    assert completed_job.status == "failed"
    assert "Aucun sous-titre disponible" in completed_job.message


def test_video_detail_back_link_returns_to_channel_page(monkeypatch):
    db = make_session()
    video = add_video(db)

    response = site(db).get(
        f"/videos/{video.id}?next=/videos%3Fchannel_id%3D{video.channel_id}%26page%3D2"
    )
    rendered = response.text

    assert response.status_code == 200
    assert f'href="/videos?channel_id={video.channel_id}&amp;page=2"' in rendered
    assert "← Retour à la chaîne" in rendered


def test_video_detail_back_link_returns_to_playlist_page(monkeypatch):
    db = make_session()
    video = add_video(db)

    response = site(db).get(f"/videos/{video.id}?next=/playlists/7")
    rendered = response.text

    assert response.status_code == 200
    assert 'href="/playlists/7"' in rendered
    assert "← Retour à la playlist" in rendered


async def collect_streaming_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def test_video_audio_supports_range_requests_for_safari(tmp_path):
    db = make_session()
    folder = tmp_path / "audio"
    folder.mkdir()
    audio = folder / "episode.mp3"
    audio.write_bytes(b"0123456789")
    video = Video(
        yt_video_id="range123",
        title="Audio avec range",
        url="https://youtube.com/watch?v=range123",
        media_type="audio",
        folder_path=str(folder),
        audio_path=str(audio),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/videos/{video.id}/audio",
            "headers": [(b"range", b"bytes=2-5")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = api_media.video_audio(video.id, request, db)

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert response.media_type == "audio/mpeg"
    assert asyncio.run(collect_streaming_body(response)) == b"2345"


def test_video_file_supports_range_requests_for_safari(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    video_file = folder / "episode.mp4"
    video_file.write_bytes(b"0123456789")
    video = Video(
        yt_video_id="videorange123",
        title="Vidéo avec range",
        url="https://youtube.com/watch?v=videorange123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(video_file),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/videos/{video.id}/video",
            "headers": [(b"range", b"bytes=1-4")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = api_media.video_file(video.id, request, db)

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 1-4/10"
    assert response.headers["content-length"] == "4"
    assert response.media_type == "video/mp4"
    assert asyncio.run(collect_streaming_body(response)) == b"1234"


def test_video_file_head_exposes_media_headers_for_safari(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    video_file = folder / "episode.mp4"
    video_file.write_bytes(b"0123456789")
    video = Video(
        yt_video_id="videohead123",
        title="Vidéo avec head",
        url="https://youtube.com/watch?v=videohead123",
        media_type="video",
        folder_path=str(folder),
        video_path=str(video_file),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    request = Request(
        {
            "type": "http",
            "method": "HEAD",
            "path": f"/api/videos/{video.id}/video",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = api_media.video_file_head(video.id, request, db)

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "10"
    assert response.media_type == "video/mp4"


def test_metadata_video_detail_exposes_audio_and_video_download_actions(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    video = Video(
        channel=channel,
        yt_video_id="meta123",
        title="Une vidéo en métadonnées",
        url="https://youtube.com/watch?v=meta123",
        media_type="metadata",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        folder_path="/media/video",
        thumbnail_path="/media/video/thumbnail.webp",
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=1024,
    )
    db.add(video)
    db.commit()

    response = site(db).get(f"/videos/{video.id}")
    rendered = response.text

    assert "Métadonnées" in rendered
    assert 'class="video-player-panel media-thumbnail-panel"' in rendered
    assert f'src="/api/videos/{video.id}/thumbnail"' in rendered
    assert "data-video-format-actions" in rendered
    assert f'data-video-id="{video.id}"' in rendered
    assert 'data-allow-delete="true"' in rendered
    assert 'title="Télécharger l’audio"' in rendered
    assert 'title="Télécharger la vidéo"' in rendered
    assert "data-format-quality-popover" in rendered
    assert f'name="next" value="/videos/{video.id}"' in rendered


def test_video_detail_exposes_subtitle_track_and_route(tmp_path):
    db = make_session()
    video = add_video(db)
    folder = tmp_path / "video"
    folder.mkdir()
    subtitle = folder / "subs.vtt"
    subtitle.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nBonjour\n", encoding="utf-8")
    video.folder_path = str(folder)
    video.subtitle_path = str(subtitle)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text
    response = api_media.video_subtitles(video.id, db)

    # Pas d'attribut `default` : il forcerait l'affichage à chaque chargement,
    # même quand les sous-titres sont désactivés dans le lecteur (iPhone).
    assert (
        f'<track kind="subtitles" src="/api/videos/{video.id}/subtitles" label="Sous-titres">'
        in rendered
    )
    assert str(response.path) == str(subtitle)
    assert response.media_type == "text/vtt; charset=utf-8"


def test_download_form_does_not_force_a_subtitle_language(monkeypatch):
    # A forced language asks YouTube for an auto-translation (HTTP 429): the form leaves the track choice to the server.
    db = make_session()
    scheduled = record_calls(monkeypatch, api_imports, "run_manual_download_job")

    response = post_form(
        db,
        "/videos/download",
        {
            "url": "https://youtube.com/watch?v=en123",
            "media_type": ["metadata"],
            "download_transcript": "true",
            "next": "/videos/import",
        },
    )

    assert response.headers["location"].startswith("/videos/import?message=")
    assert scheduled[0][5] is None


def test_import_page_has_form_without_subtitle_language_and_menu_entry():
    db = make_session()

    rendered = site(db).get("/videos/import").text

    assert 'action="/videos/download"' in rendered
    assert 'name="url"' in rendered
    assert "subtitle_language" not in rendered
    assert "subtitle_source" not in rendered
    assert 'aria-current="page">Import</a>' in rendered
    # Metadata and transcript are always imported: hidden fields, no checkbox.
    assert '<input type="hidden" name="media_type" value="metadata">' in rendered
    assert '<input type="hidden" name="download_transcript" value="true">' in rendered
    assert "Télécharger le transcript" not in rendered
    assert 'value="metadata" data-metadata-format' not in rendered
    assert 'name="media_type" type="checkbox" value="video" data-media-format' in rendered
    assert 'name="media_type" type="checkbox" value="audio" data-media-format' in rendered
    # Posted order is the job's run order: media first, metadata after.
    assert rendered.index('value="audio" data-media-format') < rendered.index(
        '<input type="hidden" name="media_type" value="metadata">'
    )
    assert rendered.index('<a href="/videos/import">Import</a>') < rendered.index(
        '<a href="/dashboard/nouveautes">Nouveautés</a>'
    )


def test_import_page_route_is_not_shadowed_by_video_detail():
    response = site(make_session()).get("/videos/import")

    assert response.status_code == 200
    assert 'action="/videos/download"' in response.text


def test_download_form_queues_job(monkeypatch):
    db = make_session()
    scheduled = record_calls(monkeypatch, api_imports, "run_manual_download_job")

    response = post_form(
        db,
        "/videos/download",
        {
            "url": "https://youtube.com/watch?v=abc123",
            "media_type": ["audio"],
            "download_transcript": "true",
            "next": "/videos",
        },
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 303
    assert job.status == "queued"
    assert scheduled == [
        (
            job.id,
            "https://youtube.com/watch?v=abc123",
            ["audio", "metadata"],
            True,
            None,
            None,
            "both",
            "1080",
        )
    ]

    status = download_requests.job_status(db, job.id)
    assert status["status"] == "queued"
    assert status["done"] is False


def test_download_form_accepts_metadata_only_job(monkeypatch):
    db = make_session()
    scheduled = record_calls(monkeypatch, api_imports, "run_manual_download_job")

    response = post_form(
        db,
        "/videos/download",
        {
            "url": "https://youtube.com/watch?v=meta123",
            "media_type": ["metadata"],
            "download_transcript": "true",
            "next": "/videos",
        },
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 303
    assert job.status == "queued"
    assert scheduled == [
        (
            job.id,
            "https://youtube.com/watch?v=meta123",
            ["metadata"],
            True,
            None,
            None,
            "both",
            "1080",
        )
    ]


def test_download_form_queues_category_labels(monkeypatch):
    db = make_session()
    scheduled = record_calls(monkeypatch, api_imports, "run_manual_download_job")

    response = post_form(
        db,
        "/videos/download",
        {
            "url": "https://youtube.com/watch?v=cat123",
            "media_type": ["metadata"],
            "preset_categories": ["maker", "science"],
            "custom_categories": "Interview, maker",
            "next": "/videos",
        },
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 303
    assert scheduled == [
        (
            job.id,
            "https://youtube.com/watch?v=cat123",
            ["metadata"],
            False,
            "maker,science,interview",
            None,
            "both",
            "1080",
        )
    ]
    assert "interview" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_video_detail_page_returns_404_for_unknown_video():
    db = make_session()

    response = site(db).get("/videos/999")

    assert response.status_code == 404


def test_videos_page_shows_only_local_channel_videos(monkeypatch):
    db = make_session()
    video = add_video(db)
    video.channel.category_labels = "maker"
    video.channel.yt_channel_id = "UC123"
    metadata = Video(
        channel=video.channel,
        yt_video_id="metadata-channel-123",
        title="Fiche de chaîne sans média",
        url="https://youtube.com/watch?v=metadata-channel-123",
        media_type="metadata",
        folder_path="/media/metadata-channel",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(metadata)
    db.commit()

    response = site(db).get(f"/videos?channel_id={video.channel_id}")
    rendered = response.text

    # The channel name is the link to YouTube; the counts live in the "⋯" menu.
    assert '<h1 class="channel-name">' in rendered
    assert "https://example.test/channel" in rendered
    assert "<dt>Fiches</dt><dd>2</dd>" in rendered
    assert "Une vidéo à lire localement" in rendered
    assert "Fiche de chaîne sans média" in rendered
    assert "Vidéo pas encore téléchargée" not in rendered
    assert f'href="/videos/{video.id}?next=/videos%3Fchannel_id%3D{video.channel_id}"' in rendered
    assert f'name="next" value="/videos?channel_id={video.channel_id}"' in rendered
    assert f'action="/channels/{video.channel_id}/categories"' in rendered
    assert 'name="preset_categories" type="checkbox" value="maker" checked' in rendered
    assert "Enregistrer les labels" in rendered
    assert f'action="/channels/{video.channel_id}/import-metadata"' in rendered
    assert "Chercher les nouvelles vidéos" in rendered
    assert "Explorer la suite" in rendered
    assert "Importer infos" not in rendered
    assert "UC123" not in rendered
    assert "URL YouTube" not in rendered
    assert 'name="media_type" type="checkbox" value="video" data-media-format>' not in rendered
    assert 'name="media_type" type="checkbox" value="audio" data-media-format' not in rendered
    assert (
        'name="media_type" type="checkbox" value="metadata" data-metadata-format checked'
        not in rendered
    )
    assert 'value="metadata" checked' in rendered
    assert 'value="transcript" checked' in rendered
    assert 'name="rated" type="checkbox" value="1"' in rendered


def test_videos_page_searches_titles_and_channels(monkeypatch):
    db = make_session()
    searched = add_video(db)
    searched.title = "Cours architecture locale"
    searched.channel.name = "Atelier recherche"
    other = Video(
        channel=searched.channel,
        yt_video_id="other-video",
        title="Cuisine rapide",
        url="https://youtube.com/watch?v=other-video",
        media_type="video",
        folder_path="/media/other",
        video_path="/media/other/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(other)
    db.commit()

    response = site(db).get("/videos?q=architecture")
    rendered = response.text

    assert "Cours architecture locale" in rendered
    assert "Cuisine rapide" not in rendered
    assert 'name="q" type="search" value="architecture"' in rendered


def test_search_rank_matches_every_word_ignoring_order_case_and_accents():
    groups = [["Tuto Python à l'École"], ["Atelier"], ["https://example.test/x"]]

    assert search.search_rank("python tuto", groups) == 0
    assert search.search_rank("ECOLE", groups) == 0
    assert search.search_rank("tuto atelier", groups) == 1
    assert search.search_rank("example.test python", groups) == 2
    assert search.search_rank("python cuisine", groups) is None
    assert search.search_rank("", groups) == 0


def test_videos_page_search_ranks_title_matches_first_and_searches_notes(monkeypatch):
    db = make_session()
    by_note = add_video(db)
    by_note.title = "Episode 12"
    by_note.comment = "Très bon passage sur le jardinage"
    by_note.downloaded_at = datetime(2026, 2, 1, tzinfo=UTC)
    by_title = Video(
        channel=by_note.channel,
        yt_video_id="title-video",
        title="Jardinage d'été",
        url="https://youtube.com/watch?v=title-video",
        media_type="video",
        folder_path="/media/title",
        video_path="/media/title/video.mp4",
        downloaded_at=datetime(2026, 1, 1, tzinfo=UTC),
        transcript_status=TranscriptStatus.missing,
    )
    db.add(by_title)
    db.commit()

    rendered = site(db).get("/videos?q=ete+Jardinage").text

    assert "Episode 12" not in rendered
    assert "Jardinage d&#39;été" in rendered
    assert 'name="q" type="search" value="ete Jardinage"' in rendered

    rendered = site(db).get("/videos?q=jardinage").text
    frame = rendered[
        rendered.index('<turbo-frame id="library-results"') : rendered.index("</turbo-frame>")
    ]

    # The note match is the most recent import, yet the title match comes first.
    assert frame.index("Jardinage d&#39;été") < frame.index("Episode 12")


def test_videos_page_search_without_result_names_the_query(monkeypatch):
    db = make_session()
    add_video(db)

    rendered = site(db).get("/videos?q=introuvable").text

    assert "Aucun résultat pour « introuvable »." in rendered
    assert 'data-live-search="library-results"' in rendered


def test_videos_page_filters_by_selected_assets(monkeypatch):
    db = make_session()
    video = add_video(db)
    channel = video.channel
    audio = Video(
        channel=channel,
        yt_video_id="audio123",
        title="Audio local",
        url="https://youtube.com/watch?v=audio123",
        media_type="audio",
        folder_path="/media/audio",
        audio_path="/media/audio/audio.mp3",
        transcript_status=TranscriptStatus.missing,
    )
    metadata = Video(
        channel=channel,
        yt_video_id="metadata123",
        title="Métadonnées seules",
        url="https://youtube.com/watch?v=metadata123",
        media_type="metadata",
        folder_path="/media/metadata",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all([audio, metadata])
    db.commit()

    default_response = site(db).get("/videos")
    default_rendered = default_response.text

    assert "Une vidéo à lire localement" in default_rendered
    assert "Audio local" in default_rendered
    assert "Métadonnées seules" not in default_rendered

    metadata_response = site(db).get("/videos?asset_filters=1&asset=metadata")
    metadata_rendered = metadata_response.text

    assert "Métadonnées seules" in metadata_rendered
    assert "Une vidéo à lire localement" not in metadata_rendered
    assert "Audio local" not in metadata_rendered


def test_videos_page_sorts_by_import_date_by_default_and_channel_by_publication(monkeypatch):
    db = make_session()
    older_publication_recent_import = add_video(db)
    older_publication_recent_import.title = "Import récent"
    older_publication_recent_import.published_at = datetime(2026, 1, 1, tzinfo=UTC)
    older_publication_recent_import.downloaded_at = datetime(2026, 6, 3, tzinfo=UTC)
    recent_publication_older_import = Video(
        channel=older_publication_recent_import.channel,
        yt_video_id="recent-publication",
        title="Publication récente",
        url="https://youtube.com/watch?v=recent-publication",
        media_type="video",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        downloaded_at=datetime(2026, 6, 1, tzinfo=UTC),
        folder_path="/media/recent-publication",
        video_path="/media/recent-publication/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(recent_publication_older_import)
    db.commit()

    default_rendered = site(db).get("/videos").text
    default_list = default_rendered[default_rendered.index('<div class="video-row-list">') :]

    assert default_list.index("Import récent") < default_list.index("Publication récente")
    assert '<option value="imported" selected>Import récent</option>' in default_rendered

    published_rendered = site(db).get("/videos?sort=published").text
    published_list = published_rendered[published_rendered.index('<div class="video-row-list">') :]

    assert published_list.index("Publication récente") < published_list.index("Import récent")
    assert '<option value="published" selected>Publication récente</option>' in published_rendered

    channel_rendered = (
        site(db).get(f"/videos?channel_id={older_publication_recent_import.channel_id}").text
    )
    channel_list = channel_rendered[
        channel_rendered.index('<div class="video-row-list channel-video-grid"') :
    ]

    assert channel_list.index("Publication récente") < channel_list.index("Import récent")
    assert 'name="sort" type="radio" value="published" checked' in channel_rendered


def test_videos_page_filters_manual_imports(monkeypatch):
    db = make_session()
    manual = add_video(db)
    manual.download_source = "manual"
    manual.imported_via_form = True
    auto = Video(
        channel=manual.channel,
        yt_video_id="auto-video",
        title="Vidéo automatique",
        url="https://youtube.com/watch?v=auto-video",
        media_type="video",
        download_source="auto",
        folder_path="/media/auto",
        video_path="/media/auto/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(auto)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&asset=imported")
    rendered = response.text

    assert "Manuelles" in rendered
    assert "Manuelle" in rendered
    assert manual.title in rendered
    assert auto.title not in rendered
    assert 'name="asset" type="checkbox" value="imported" checked' in rendered


def test_videos_page_does_not_treat_manual_media_on_channel_metadata_as_form_import(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    channel_metadata = Video(
        channel=channel,
        yt_video_id="channel-metadata",
        title="Fiche issue de chaîne",
        url="https://youtube.com/watch?v=channel-metadata",
        media_type="video",
        download_source="manual",
        imported_via_form=False,
        folder_path="/media/channel-metadata",
        video_path="/media/channel-metadata/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(channel_metadata)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&asset=imported")
    rendered = response.text

    assert "Fiche issue de chaîne" not in rendered


def test_videos_page_filters_by_rated_videos(monkeypatch):
    db = make_session()
    rated = add_video(db)
    rated.rating = 4
    channel = rated.channel
    regular = Video(
        channel=channel,
        yt_video_id="regular123",
        title="Vidéo non notée",
        url="https://youtube.com/watch?v=regular123",
        media_type="video",
        folder_path="/media/regular",
        video_path="/media/regular/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(regular)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&filter_mode=and&asset=video&rated=1")
    rendered = response.text

    assert response.status_code == 200
    assert rated.title in rendered
    assert regular.title not in rendered
    assert 'name="asset_filter_mode" type="radio" value="and" checked' in rendered
    assert 'name="rated" type="checkbox" value="1" checked' in rendered
    assert (
        'class="rating-control rating-control-minimal video-row-rating rating-tier-4"' in rendered
    )
    assert "rating-star-filled" in rendered
    assert (
        f'href="/videos/{rated.id}?next=/videos%3Fasset_filters%3D1%26filter_mode%3Dand%26asset%3Dvideo%26rated%3D1"'
        in rendered
    )
    assert (
        'name="next" value="/videos?asset_filters=1&amp;filter_mode=and&amp;asset=video&amp;rated=1"'
        in rendered
    )


def test_videos_page_renders_default_rated_sub_library(monkeypatch):
    db = make_session()
    rated = add_video(db)
    rated.rating = 4
    db.commit()

    response = site(db).get(
        "/videos?asset_filters=1&asset_filter_mode=or&category_filter_mode=or&rated=1"
    )
    rendered = response.text

    assert rated.title in rendered
    assert '<nav class="library-subnav" aria-label="Sous-bibliothèques">' in rendered
    assert (
        '<a class="lg active" href="/videos?asset_filters=1&amp;asset_filter_mode=or&amp;category_filter_mode=or&amp;rated=1">Notés</a>'
        in rendered
    )


def test_videos_page_empty_sub_library_filters_show_all_videos(monkeypatch):
    db = make_session()
    video = add_video(db)

    response = site(db).get("/videos?asset_filters=1&asset_filter_mode=or&category_filter_mode=or")
    rendered = response.text

    assert video.title in rendered


def test_videos_page_or_filter_mode_matches_any_selected_condition(monkeypatch):
    db = make_session()
    rated_metadata = add_video(db)
    rated_metadata.media_type = "metadata"
    rated_metadata.video_path = None
    rated_metadata.metadata_path = "/media/metadata/info.json"
    rated_metadata.rating = 5
    regular_video = Video(
        channel=rated_metadata.channel,
        yt_video_id="regular-video",
        title="Vidéo non notée",
        url="https://youtube.com/watch?v=regular-video",
        media_type="video",
        folder_path="/media/regular-video",
        video_path="/media/regular-video/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(regular_video)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&filter_mode=or&asset=video&rated=1")
    rendered = response.text

    assert rated_metadata.title in rendered
    assert regular_video.title in rendered
    assert 'name="asset_filter_mode" type="radio" value="or" checked' in rendered


def test_videos_page_excludes_selected_asset_labels(monkeypatch):
    db = make_session()
    local_video = add_video(db)
    metadata = Video(
        channel=local_video.channel,
        yt_video_id="metadata-only",
        title="Fiche métadonnées seule",
        url="https://youtube.com/watch?v=metadata-only",
        media_type="metadata",
        folder_path="/media/metadata-only",
        metadata_path="/media/metadata-only/info.json",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(metadata)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&exclude_asset=metadata")
    rendered = response.text

    assert local_video.title in rendered
    assert "Fiche métadonnées seule" not in rendered
    assert 'name="exclude_asset" type="checkbox" value="metadata" checked' in rendered


def test_videos_page_filters_by_category_labels(monkeypatch):
    db = make_session()
    maker = add_video(db)
    maker.category_labels = "maker,science"
    cooking = Video(
        channel=maker.channel,
        yt_video_id="cuisine-video",
        title="Cuisine locale",
        url="https://youtube.com/watch?v=cuisine-video",
        media_type="video",
        folder_path="/media/cuisine",
        video_path="/media/cuisine/video.mp4",
        category_labels="cuisine",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(cooking)
    db.commit()

    response = site(db).get(
        "/videos?asset_filters=1&filter_mode=and&category=maker&category=science"
    )
    rendered = response.text

    assert maker.title in rendered
    assert "Cuisine locale" not in rendered
    assert 'name="category" type="checkbox" value="maker" checked' in rendered
    assert 'name="category" type="checkbox" value="science" checked' in rendered
    assert 'name="category_filter_mode" type="radio" value="and" checked' in rendered
    assert '<details class="filter-group filter-group-wide filter-collapse" open' not in rendered
    assert ">maker</span>" in rendered
    assert ">science</span>" in rendered


def test_videos_page_excludes_selected_category_labels(monkeypatch):
    db = make_session()
    maker = add_video(db)
    maker.category_labels = "maker,science"
    cooking = Video(
        channel=maker.channel,
        yt_video_id="cuisine-video",
        title="Cuisine locale",
        url="https://youtube.com/watch?v=cuisine-video",
        media_type="video",
        folder_path="/media/cuisine",
        video_path="/media/cuisine/video.mp4",
        category_labels="cuisine",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(cooking)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&asset=video&exclude_category=maker")
    rendered = response.text

    assert maker.title not in rendered
    assert "Cuisine locale" in rendered
    assert 'name="exclude_category" type="checkbox" value="maker" checked' in rendered


def test_videos_page_filters_category_without_shorts(monkeypatch):
    db = make_session()
    regular = add_video(db)
    regular.category_labels = "cuisine"
    short = Video(
        channel=regular.channel,
        yt_video_id="short-cuisine",
        title="Short cuisine",
        url="https://youtube.com/shorts/short-cuisine",
        media_type="video",
        folder_path="/media/short-cuisine",
        video_path="/media/short-cuisine/video.mp4",
        category_labels="cuisine",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(short)
    db.commit()

    response = site(db).get("/videos?asset_filters=1&category=cuisine&exclude_asset=shorts")
    rendered = response.text

    assert regular.title in rendered
    assert "Short cuisine" not in rendered
    assert 'name="category" type="checkbox" value="cuisine" checked' in rendered
    assert 'name="exclude_asset" type="checkbox" value="shorts" checked' in rendered


def test_videos_page_uses_separate_asset_and_category_filter_modes(monkeypatch):
    db = make_session()
    full_match = add_video(db)
    full_match.title = "Vidéo maker science"
    full_match.category_labels = "maker,science"
    maker_only = Video(
        channel=full_match.channel,
        yt_video_id="maker-only",
        title="Vidéo maker seule",
        url="https://youtube.com/watch?v=maker-only",
        media_type="video",
        folder_path="/media/maker-only",
        video_path="/media/maker-only/video.mp4",
        category_labels="maker",
        transcript_status=TranscriptStatus.missing,
    )
    metadata_match = Video(
        channel=full_match.channel,
        yt_video_id="metadata-match",
        title="Fiche maker science",
        url="https://youtube.com/watch?v=metadata-match",
        media_type="metadata",
        folder_path="/media/metadata-match",
        metadata_path="/media/metadata-match/info.json",
        category_labels="maker,science",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all([maker_only, metadata_match])
    db.commit()

    response = site(db).get(
        "/videos?asset_filters=1&asset_filter_mode=or&category_filter_mode=and&asset=video&category=maker&category=science"
    )
    rendered = response.text

    assert "Vidéo maker science" in rendered
    assert "Vidéo maker seule" not in rendered
    assert "Fiche maker science" not in rendered
    assert 'name="asset_filter_mode" type="radio" value="or" checked' in rendered
    assert 'name="category_filter_mode" type="radio" value="and" checked' in rendered


def test_video_categories_form_saves_presets_and_custom_labels():
    db = make_session()
    video = add_video(db)

    response = post_form(
        db,
        f"/videos/{video.id}/categories",
        {
            "preset_categories": ["maker", "science"],
            "custom_categories": "Interview, maker",
            "next": f"/videos/{video.id}",
        },
    )

    assert response.headers["location"] == f"/videos/{video.id}"
    assert video.category_labels == "maker,science,interview"
    assert "interview" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_videos_page_accepts_empty_channel_filter(monkeypatch):
    db = make_session()
    video = add_video(db)

    response = site(db).get("/videos?asset_filters=1&channel_id=&asset=video")
    rendered = response.text

    assert response.status_code == 200
    assert "Bibliothèque" in rendered
    assert video.title in rendered


def test_channel_metadata_import_form_queues_the_job_and_redirects(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    db.add(channel)
    db.commit()
    scheduled = record_calls(monkeypatch, api_channels, "run_channel_metadata_import_job")

    response = post_form(
        db,
        f"/channels/{channel.id}/import-metadata",
        {"page": "2", "next": f"/videos?channel_id={channel.id}"},
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos?channel_id={channel.id}&message=")
    assert job.status == "queued"
    assert job.channel_id == channel.id
    assert scheduled == [(job.id, channel.id, 2, "videos")]

    status = download_requests.job_status(db, job.id)
    assert status["status"] == "queued"
    assert status["done"] is False


def test_channel_metadata_import_job_imports_one_page(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    job = DownloadJob(channel=channel, status="queued", message="queued")
    db.add(job)
    db.commit()
    calls = []
    monkeypatch.setattr(downloads, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        downloads,
        "scan_channel_section",
        lambda db, channel, **kwargs: calls.append(kwargs) or 25,
    )

    downloads.run_channel_metadata_import_job(job.id, channel.id, page=1)

    assert len(calls) == 1
    assert callable(calls[0].pop("should_stop"))
    assert calls == [
        {
            "page": 1,
            "page_size": downloads.CHANNEL_VIDEO_PAGE_SIZE,
            "max_pages": 1,
            "section": "videos",
        }
    ]
    assert job.status == "metadata"
    assert job.message == "25 fiches vidéos importées pour Chaîne test."


def test_channel_next_import_button_uses_next_youtube_page(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    db.add(channel)
    db.commit()
    for index in range(25):
        db.add(
            Video(
                channel_id=channel.id,
                yt_video_id=f"video{index}",
                title=f"Vidéo {index}",
                url=f"https://youtube.com/watch?v=video{index}",
                media_type="metadata",
                folder_path=f"/media/video{index}",
                transcript_status=TranscriptStatus.missing,
            )
        )
    db.commit()

    response = site(db).get(f"/videos?channel_id={channel.id}")
    rendered = response.text

    assert 'name="section" value="videos"' in rendered
    assert f'<input type="hidden" name="channel_id" value="{channel.id}">' in rendered
    assert 'input name="section" type="radio" value="videos" checked' in rendered
    assert 'input name="section" type="radio" value="shorts"' in rendered
    assert "Chercher les nouvelles vidéos" in rendered
    assert 'name="page" value="2"' in rendered
    assert "Explorer la suite" in rendered


def test_channel_shorts_page_filters_local_videos_and_imports_shorts(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test", rating=4)
    regular = Video(
        channel=channel,
        yt_video_id="regular123",
        title="Vidéo longue",
        url="https://www.youtube.com/watch?v=regular123",
        media_type="video",
        folder_path="/media/regular",
        video_path="/media/regular/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    short = Video(
        channel=channel,
        yt_video_id="short123",
        title="Short vertical",
        url="https://www.youtube.com/shorts/short123",
        media_type="video",
        folder_path="/media/short",
        video_path="/media/short/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all([channel, regular, short])
    db.commit()

    response = site(db).get(f"/videos?channel_id={channel.id}&section=shorts")
    rendered = response.text

    assert "Short vertical" in rendered
    assert "Vidéo longue" not in rendered
    assert f'action="/channels/{channel.id}/rating"' in rendered
    assert "rating-tier-4" in rendered
    assert "<dt>Vidéos téléchargées</dt>" in rendered
    assert "<dd>1</dd>" in rendered
    assert "<dt>Shorts téléchargés</dt>" in rendered
    assert 'input name="section" type="radio" value="shorts" checked' in rendered
    assert "Chercher les nouveaux shorts" in rendered


@pytest.mark.parametrize(
    ("videos_bell", "shorts_bell", "query", "expected"),
    [
        (False, True, "", "shorts"),
        (True, True, "", "videos"),
        (False, False, "", "videos"),
        (True, False, "", "videos"),
        (False, True, "&section=videos", "videos"),
    ],
)
def test_channel_page_default_section_follows_shorts_bell(
    videos_bell, shorts_bell, query, expected
):
    db = make_session()
    channel = Channel(
        name="Canal",
        url="https://www.youtube.com/@canal",
        auto_metadata_enabled=videos_bell,
        auto_shorts_enabled=shorts_bell,
    )
    db.add_all(
        [
            channel,
            Video(
                channel=channel,
                yt_video_id="regular123",
                title="Vidéo longue",
                url="https://www.youtube.com/watch?v=regular123",
                media_type="video",
                folder_path="/media/regular",
                video_path="/media/regular/video.mp4",
                transcript_status=TranscriptStatus.missing,
            ),
            Video(
                channel=channel,
                yt_video_id="short123",
                title="Short vertical",
                url="https://www.youtube.com/shorts/short123",
                media_type="video",
                folder_path="/media/short",
                video_path="/media/short/video.mp4",
                transcript_status=TranscriptStatus.missing,
            ),
        ]
    )
    db.commit()

    rendered = site(db).get(f"/videos?channel_id={channel.id}{query}").text

    assert ("Short vertical" in rendered) == (expected == "shorts")
    assert ("Vidéo longue" in rendered) == (expected == "videos")


def test_content_views_only_link_to_raton_pages():
    db = make_session()
    video = add_video(db)
    channel = video.channel

    videos_playback.record_playback_activity(db, video, "video", 12, 120, 12)
    client = site(db)

    dashboard = client.get("/dashboard/historique").text
    channels = client.get("/channels?rated=false").text
    detail = client.get(f"/videos/{video.id}").text

    assert f'href="/videos/{video.id}"' in dashboard
    assert f'href="/videos?channel_id={channel.id}"' in dashboard
    assert f'href="/videos?channel_id={channel.id}"' in channels
    assert f'action="/videos/{video.id}/rating"' in detail
    for rendered in (dashboard, channels, detail):
        hrefs = re.findall(r'href="([^"]+)"', rendered)
        assert not any("youtube.com" in href.lower() for href in hrefs)


def test_video_detail_exposes_server_resume_position_per_media_kind():
    db = make_session()
    video = add_video(db)
    base = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    for offset, media_type, position in ((0, "video", 120), (1, "audio", 45), (2, "video", 252.5)):
        videos_playback.record_playback_activity(db, video, media_type, position, 600, 10)
        job = db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played")
            .order_by(DownloadJob.id.desc())
        ).first()
        job.created_at = base + timedelta(minutes=offset)
        db.commit()

    positions = videos_playback.latest_playback_positions(db, video.id)

    assert positions["video"] == {
        "position_seconds": 252.5,
        "at_ms": int((base + timedelta(minutes=2)).timestamp() * 1000),
    }
    assert positions["audio"] == {
        "position_seconds": 45,
        "at_ms": int((base + timedelta(minutes=1)).timestamp() * 1000),
    }

    rendered = site(db).get(f"/videos/{video.id}").text

    assert 'data-resume-server-position="252.5"' in rendered
    assert f'data-resume-server-at="{positions["video"]["at_ms"]}"' in rendered


def test_video_detail_omits_server_resume_position_without_playback():
    db = make_session()
    video = add_video(db)

    rendered = site(db).get(f"/videos/{video.id}").text

    assert videos_playback.latest_playback_positions(db, video.id) == {}
    assert "data-resume-server-position" not in rendered


def test_video_activity_logs_media_playback():
    db = make_session()
    video = add_video(db)

    videos_playback.record_playback_activity(db, video, "video", 252, 600, 83)
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "played"))

    assert job is not None
    assert job.video_id == video.id
    assert job.channel_id == video.channel_id
    payload = json.loads(job.message)
    assert payload["type"] == "playback"
    assert payload["action"] == "Reprise"
    assert payload["media_label"] == "vidéo"
    assert payload["position_seconds"] == 252
    assert payload["duration_seconds"] == 600
    assert payload["watched_seconds"] == 83


def test_video_activity_sets_watched_at_at_ninety_percent():
    db = make_session()
    video = add_video(db)

    videos_playback.record_playback_activity(db, video, "video", 300, 600, 10)
    assert db.get(Video, video.id).watched_at is None

    videos_playback.record_playback_activity(db, video, "video", 540, 600, 10)
    assert db.get(Video, video.id).watched_at is not None


def test_library_pages_share_the_nouveautes_historique_exploration_subnav():
    db = make_session()

    rendered = site(db).get("/dashboard/nouveautes").text

    assert 'class="library-subnav"' in rendered
    assert (
        '<a class="lg" href="/dashboard/nouveautes" aria-current="page">Nouveautés</a>' in rendered
    )
    assert '<a class="lg" href="/dashboard/historique" >Historique</a>' in rendered
    assert '<a class="lg" href="/videos" >Exploration</a>' in rendered
    assert 'href="/videos?focus=search"' not in rendered
    assert 'aria-label="Recherche"' not in rendered


def make_new_video(db, channel, index, is_new=True):
    video = Video(
        channel=channel,
        yt_video_id=f"new-{channel.name}-{index}",
        title=f"Nouveauté {index}",
        url=f"https://www.youtube.com/watch?v=new-{channel.name}-{index}",
        media_type="video",
        folder_path=f"/media/new-{channel.name}-{index}",
        video_path=f"/media/new-{channel.name}-{index}/video.mp4",
        transcript_status=TranscriptStatus.missing,
        is_new=is_new,
        downloaded_at=datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=index),
    )
    db.add(video)
    return video


def test_dashboard_new_videos_page_paginates_by_channel_ten_at_a_time():
    db = make_session()
    channels = [
        Channel(
            url=f"https://example.test/new{i}", name=f"Chaîne {i:02d}", auto_metadata_enabled=True
        )
        for i in range(15)
    ]
    db.add_all(channels)
    for channel_index, channel in enumerate(channels):
        make_new_video(db, channel, channel_index)
    db.commit()

    page_one = site(db).get("/dashboard/nouveautes")
    rendered_one = page_one.text
    page_two = site(db).get("/dashboard/nouveautes?page=2")
    rendered_two = page_two.text

    assert rendered_one.count('class="video-stack"') == 10
    assert "Chaîne 14" in rendered_one
    assert "Chaîne 04" not in rendered_one
    assert rendered_two.count('class="video-stack"') == 5
    assert "Chaîne 04" in rendered_two
    assert "Page 1 / 2" in rendered_one


def test_dashboard_new_videos_page_stack_caps_at_ten_most_recent_videos():
    db = make_session()
    channel = Channel(
        url="https://example.test/busy", name="Chaîne active", auto_metadata_enabled=True
    )
    db.add(channel)
    for index in range(15):
        make_new_video(db, channel, index)
    db.commit()

    rendered = site(db).get("/dashboard/nouveautes").text

    assert rendered.count('<article class="video-row') == 10
    assert "Nouveauté 14" in rendered
    assert "Nouveauté 4" not in rendered
    assert "data-video-stack-carousel" in rendered
    assert "data-video-stack-previous" in rendered
    assert "1 / 10" not in rendered


def test_dashboard_new_videos_page_still_shows_already_visited_videos():
    db = make_session()
    channel = Channel(
        url="https://example.test/visited", name="Chaîne visitée", auto_metadata_enabled=True
    )
    db.add(channel)
    make_new_video(db, channel, 0, is_new=False)
    db.commit()

    rendered = site(db).get("/dashboard/nouveautes").text

    assert "Nouveauté 0" in rendered


def test_dashboard_new_videos_page_excludes_channels_without_the_bell():
    db = make_session()
    followed = Channel(
        url="https://example.test/followed", name="Chaîne suivie", auto_metadata_enabled=True
    )
    not_followed = Channel(url="https://example.test/playlist-origin", name="Chaîne de playlist")
    db.add_all([followed, not_followed])
    make_new_video(db, followed, 0)
    make_new_video(db, not_followed, 0)
    db.commit()

    rendered = site(db).get("/dashboard/nouveautes").text

    assert "Chaîne suivie" in rendered
    assert "Chaîne de playlist" not in rendered


def test_dashboard_new_videos_page_lists_only_the_kinds_whose_bell_is_on():
    db = make_session()
    videos_only = Channel(
        url="https://example.test/v", name="Cloche vidéos", auto_metadata_enabled=True
    )
    shorts_only = Channel(
        url="https://example.test/s", name="Cloche shorts", auto_shorts_enabled=True
    )
    both = Channel(
        url="https://example.test/b",
        name="Deux cloches",
        auto_metadata_enabled=True,
        auto_shorts_enabled=True,
    )
    silent = Channel(url="https://example.test/n", name="Sans cloche")
    db.add_all([videos_only, shorts_only, both, silent])
    for prefix, channel in (("V", videos_only), ("S", shorts_only), ("B", both), ("N", silent)):
        video = make_new_video(db, channel, 0)
        video.title = f"{prefix}-video"
        short = make_new_video(db, channel, 1)
        short.title = f"{prefix}-short"
        short.url = f"https://www.youtube.com/shorts/{short.yt_video_id}"
    db.commit()

    rendered = site(db).get("/dashboard/nouveautes").text

    for shown in ("V-video", "S-short", "B-video", "B-short"):
        assert shown in rendered
    for hidden in ("V-short", "S-video", "N-video", "N-short", "Sans cloche"):
        assert hidden not in rendered


def test_history_row_drops_the_dates_and_moves_the_file_size_next_to_the_stars():
    db = make_session()
    history_playback_jobs(db)

    rendered = site(db).get("/dashboard/historique").text
    history = rendered
    footer = history.split('<div class="video-card-footer">')[1]

    assert "Publié le" not in history
    assert "Vu le" not in history
    assert '<span class="video-card-footer-size">5.0 Mo</span>' in footer
    assert footer.index("video-card-footer-size") < footer.index("rating-control")


def test_old_reprises_url_redirects_to_historique_keeping_the_page():
    response = site(make_session()).get("/dashboard/reprises?page=3", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard/historique?page=3"


def test_dashboard_history_page_paginates_beyond_dashboard_limit():
    db = make_session()
    channel = Channel(url="https://example.test/resume", name="Chaîne reprises")
    db.add(channel)
    videos = []
    for index in range(60):
        video = Video(
            channel=channel,
            yt_video_id=f"resume-{index}",
            title=f"Reprise {index}",
            url=f"https://www.youtube.com/watch?v=resume-{index}",
            media_type="video",
            folder_path=f"/media/resume-{index}",
            video_path=f"/media/resume-{index}/video.mp4",
            transcript_status=TranscriptStatus.missing,
        )
        videos.append(video)
    db.add_all(videos)
    db.commit()
    for index, video in enumerate(videos):
        db.add(
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:04 à 0:04: Position",
                video=video,
                channel=channel,
                created_at=datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=index),
            )
        )
    db.commit()

    page_one = site(db).get("/dashboard/historique")
    rendered_one = page_one.text
    page_two = site(db).get("/dashboard/historique?page=2")
    rendered_two = page_two.text

    assert rendered_one.count('<article class="dashboard-media-row') == 50
    assert "Reprise 59" in rendered_one
    assert "Reprise 9" not in rendered_one
    assert rendered_two.count('<article class="dashboard-media-row') == 10
    assert "Reprise 9" in rendered_two


def test_history_day_groups_splits_activity_per_day_with_relative_labels():
    db = make_session()
    video = add_video(db)
    now = datetime(2025, 6, 20, 21, 0, tzinfo=UTC)

    def played_job(created_at: datetime) -> DownloadJob:
        return DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Lecture",
                    "media_label": "vidéo",
                    "position_seconds": 12,
                    "duration_seconds": 120,
                    "watched_seconds": 12,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=created_at,
        )

    jobs = [
        played_job(now - timedelta(hours=1)),
        played_job(now - timedelta(hours=3)),
        played_job(now - timedelta(days=1)),
        played_job(now - timedelta(days=3)),
    ]
    # The rows as `GET /api/historique` sends them: the back cuts the days (server's local day).
    rows = [
        record({"job_id": index, "day": job.created_at.date().isoformat(), "playback": None})
        for index, job in enumerate(jobs)
    ]

    groups = front_cards.history_days(rows, {}, now.date())

    assert [group["label"] for group in groups] == ["Aujourd’hui", "Hier", "Mar. 17 juin 2025"]
    assert [len(group["rows"]) for group in groups] == [2, 1, 1]
    assert groups[0]["full_label"] == "Ven. 20 juin 2025"
    assert groups[1]["full_label"] == "Jeu. 19 juin 2025"
    assert groups[2]["label"] == groups[2]["full_label"]
    assert groups[0]["rows"] == rows[:2]
    assert [group["seconds"] for group in groups] == [0.0, 0.0, 0.0]


def test_history_day_groups_carries_reading_time_counting_every_playback():
    db = make_session()
    video = add_video(db)
    now = datetime(2025, 6, 20, 21, 0, tzinfo=UTC)

    def played_job(created_at: datetime, watched: int) -> DownloadJob:
        return DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Lecture",
                    "media_label": "vidéo",
                    "position_seconds": watched,
                    "duration_seconds": 3600,
                    "watched_seconds": watched,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=created_at,
        )

    # Two playbacks of the same video today: the list keeps one row, the time keeps both.
    jobs = [played_job(now - timedelta(hours=1), 600), played_job(now - timedelta(hours=2), 300)]
    seconds_by_day = videos_playback.playback_seconds_by_day(jobs, now)

    rows = [record({"job_id": 1, "day": now.date().isoformat(), "playback": None})]

    groups = front_cards.history_days(
        rows, {day.isoformat(): seconds for day, seconds in seconds_by_day.items()}, now.date()
    )

    assert groups[0]["seconds"] == 900.0
    assert len(groups[0]["rows"]) == 1


def history_playback_jobs(db) -> None:
    video = add_video(db)
    other_video = Video(
        channel=video.channel,
        yt_video_id="def456",
        title="Une autre vidéo locale",
        url="https://youtube.com/watch?v=def456",
        media_type="video",
        folder_path="/media/video-2",
        video_path="/media/video-2/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(other_video)
    now = datetime.now().astimezone()
    for played_video, created_at in ((video, now), (other_video, now - timedelta(days=1))):
        db.add(
            DownloadJob(
                status="played",
                message=json.dumps(
                    {
                        "type": "playback",
                        "action": "Lecture",
                        "media_label": "vidéo",
                        "position_seconds": 12,
                        "duration_seconds": 120,
                        "watched_seconds": 12,
                    }
                ),
                video=played_video,
                channel=video.channel,
                created_at=created_at,
            )
        )
    db.commit()


def test_dashboard_history_renders_one_collapsible_block_per_day():
    db = make_session()
    history_playback_jobs(db)

    rendered = site(db).get("/dashboard/historique").text

    assert (
        '<a class="lg" href="/dashboard/historique" aria-current="page">Historique</a>' in rendered
    )
    assert rendered.count('<details class="dashboard-day-group"') == 2
    assert "<strong>Aujourd’hui</strong>" in rendered
    assert "<strong>Hier</strong>" in rendered
    assert '<span class="dashboard-day-count">1 média</span>' in rendered


def test_dashboard_history_page_groups_by_day_and_opens_every_block():
    db = make_session()
    history_playback_jobs(db)

    rendered = site(db).get("/dashboard/historique").text

    assert (
        '<a class="lg" href="/dashboard/historique" aria-current="page">Historique</a>' in rendered
    )
    assert "À reprendre" not in rendered
    assert rendered.count('<details class="dashboard-day-group" open>') == 2


def test_dashboard_history_page_renders_novideo_job_and_styled_category_label():
    db = make_session()
    channel = Channel(url="https://example.test/resume-novideo", name="Chaîne reprises stylées")
    video = Video(
        channel=channel,
        yt_video_id="resume-styled",
        title="Reprise stylée",
        url="https://www.youtube.com/watch?v=resume-styled",
        media_type="video",
        folder_path="/media/resume-styled",
        video_path="/media/resume-styled/video.mp4",
        category_labels="maker",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all([channel, video])
    db.commit()
    db.add_all(
        [
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:04 à 0:04: Position",
                video=video,
                channel=channel,
                created_at=datetime(2026, 7, 2, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Reprise audio pendant 0:04 à 0:04: Titre ancien format",
                video=None,
                channel=channel,
                created_at=datetime(2026, 7, 2, 0, 1, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Lecture audio à 0:02:",
                video=None,
                channel=channel,
                created_at=datetime(2026, 7, 2, 0, 2, tzinfo=UTC),
            ),
        ]
        + [
            # Several activity pings of one video whose row is gone since.
            DownloadJob(
                status="played",
                message=json.dumps(
                    {
                        "type": "playback",
                        "action": "Reprise",
                        "media_label": "vidéo",
                        "position_seconds": 40 + minute,
                        "duration_seconds": 120,
                        "watched_seconds": 5,
                        "title": "Vidéo supprimée depuis",
                    }
                ),
                video=None,
                channel=channel,
                created_at=datetime(2026, 7, 2, 0, 3 + minute, tzinfo=UTC),
            )
            for minute in range(2)
        ]
    )
    db.commit()

    rendered = site(db).get("/dashboard/historique").text

    # A job whose video is gone keeps showing the title it recorded, once per video.
    assert rendered.count('<span class="video-title">Vidéo supprimée depuis</span>') == 1
    assert '<span class="video-title">Titre ancien format</span>' in rendered
    assert "Reprise vidéo" not in rendered
    assert "Reprise audio" not in rendered
    # Without any recorded title, the action label is all there is to show.
    assert '<span class="video-title">Lecture audio</span>' in rendered
    assert (
        '<span class="category-label" style="--category-bg: #2563eb; --category-border: #2563eb; --category-text: #ffffff;">maker</span>'
        in rendered
    )


def test_dashboard_renders_media_playback_as_progress_bar():
    db = make_session()
    video = add_video(db)
    db.add(
        DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Reprise",
                    "media_label": "vidéo",
                    "position_seconds": 11,
                    "duration_seconds": 11,
                    "watched_seconds": 11,
                    "title": video.title,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/dashboard/historique").text

    assert "Reprise vidéo pendant 0:11 à 0:11" not in rendered
    assert "dashboard-media-row" in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' in rendered
    assert "Dim. 05 juil. 2026" in rendered
    assert video.title in rendered
    # Fully watched media hides the progress bar entirely (row is greyed out instead).
    assert "0:11 / 0:11" not in rendered
    assert 'class="video-card-progress"' not in rendered
    assert 'style="width: 100.0%"' not in rendered


def test_base_template_disables_turbo_hover_prefetch():
    db = make_session()

    rendered = site(db).get("/").text

    assert '<meta name="turbo-prefetch" content="false">' in rendered


def test_videos_page_renders_playback_progress_without_percent_label():
    db = make_session()
    video = add_video(db)
    db.add(
        DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Reprise",
                    "media_label": "vidéo",
                    "position_seconds": 275,
                    "duration_seconds": 1242,
                    "watched_seconds": 60,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/videos").text

    assert "4:35 / 20:42" in rendered
    assert 'class="video-card-progress"' in rendered
    assert "22%" not in rendered
    assert 'style="width: 22.14%"' in rendered


def test_videos_page_hides_progress_bar_and_dims_fully_watched_video():
    db = make_session()
    video = add_video(db)
    db.add(
        DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Reprise",
                    "media_label": "vidéo",
                    "position_seconds": 1242,
                    "duration_seconds": 1242,
                    "watched_seconds": 1242,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/videos").text

    assert 'class="video-card-progress"' not in rendered
    assert 'class="video-row video-row-watched"' in rendered


def test_videos_page_hides_progress_bar_without_dimming_for_musique_category():
    db = make_session()
    video = add_video(db)
    video.category_labels = "musique"
    db.add(
        DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Reprise",
                    "media_label": "vidéo",
                    "position_seconds": 275,
                    "duration_seconds": 1242,
                    "watched_seconds": 60,
                }
            ),
            video=video,
            channel=video.channel,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/videos").text

    assert 'class="video-card-progress"' not in rendered
    assert 'class="video-row video-row-watched"' not in rendered


def test_dashboard_renders_legacy_media_playback_as_progress_bar():
    db = make_session()
    video = add_video(db)
    db.add(
        DownloadJob(
            status="played",
            message="Reprise vidéo pendant 0:11 à 0:11: France Suède",
            video=video,
            channel=video.channel,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/dashboard/historique").text

    assert "Reprise vidéo pendant 0:11 à 0:11: France Suède" not in rendered
    assert "dashboard-media-row" in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' not in rendered
    assert video.title in rendered
    assert "0:11 / 0:11" in rendered
    assert 'style="width: 100.0%"' in rendered


def test_dashboard_shows_one_resume_card_per_media():
    db = make_session()
    video = add_video(db)
    db.add_all(
        [
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:04 à 0:04: Ancienne position",
                video=video,
                channel=video.channel,
                created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:11 à 0:11: Position récente",
                video=video,
                channel=video.channel,
                created_at=datetime(2026, 7, 1, 12, 5, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    rendered = site(db).get("/dashboard/historique").text

    assert rendered.count('<article class="dashboard-media-row') == 1
    assert "0:11 / 0:11" in rendered
    assert "0:04 / 0:04" not in rendered


def test_playback_time_stats_groups_today_week_and_month_by_media_kind():
    db = make_session()
    video = add_video(db)
    podcast = Video(
        channel=video.channel,
        yt_video_id="podcast123",
        title="Podcast local",
        url="https://youtube.com/watch?v=podcast123",
        media_type="audio",
        folder_path="/media/podcast",
        audio_path="/media/podcast/audio.mp3",
        category_labels="podcasts",
        transcript_status=TranscriptStatus.missing,
    )
    short = Video(
        channel=video.channel,
        yt_video_id="short123",
        title="Short local",
        url="https://youtube.com/shorts/short123",
        media_type="video",
        folder_path="/media/short",
        video_path="/media/short/video.mp4",
        transcript_status=TranscriptStatus.missing,
    )
    music = Video(
        channel=video.channel,
        yt_video_id="music123",
        title="Musique locale",
        url="https://youtube.com/watch?v=music123",
        media_type="audio",
        folder_path="/media/music",
        audio_path="/media/music/audio.mp3",
        category_labels="musique",
        transcript_status=TranscriptStatus.missing,
    )
    old_music = Video(
        channel=video.channel,
        yt_video_id="oldmusic123",
        title="Ancienne musique",
        url="https://youtube.com/watch?v=oldmusic123",
        media_type="audio",
        folder_path="/media/old-music",
        audio_path="/media/old-music/audio.mp3",
        category_labels="musique",
        transcript_status=TranscriptStatus.missing,
    )
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    def played_job(
        item: Video, media_label: str, watched_seconds: int, created_at: datetime
    ) -> DownloadJob:
        return DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Lecture",
                    "media_label": media_label,
                    "position_seconds": watched_seconds,
                    "duration_seconds": 600,
                    "watched_seconds": watched_seconds,
                }
            ),
            video=item,
            channel=item.channel,
            created_at=created_at,
        )

    jobs = [
        played_job(video, "vidéo", 120, now - timedelta(hours=1)),
        played_job(video, "vidéo", 30, now - timedelta(minutes=10)),
        played_job(short, "vidéo", 45, now - timedelta(hours=2)),
        played_job(podcast, "audio", 180, now - timedelta(days=2)),
        played_job(music, "audio", 240, now.replace(day=2)),
        played_job(old_music, "audio", 300, datetime(2026, 6, 30, 23, 0, tzinfo=UTC)),
    ]
    db.add_all([podcast, short, music, old_music, *jobs])
    db.commit()

    stats = videos_playback.playback_time_stats(jobs, now)

    assert stats["today"]["video"]["duration"] == "2m30"
    assert stats["today"]["video"]["count"] == 1
    assert stats["today"]["short"]["duration"] == "0m45"
    assert stats["today"]["short"]["count"] == 1
    assert stats["today"]["podcast"]["duration"] == "0m00"
    assert stats["today"]["podcast"]["count"] == 0
    assert stats["today"]["music"]["duration"] == "0m00"
    assert stats["week"]["video"]["duration"] == "2m30"
    assert stats["week"]["video"]["count"] == 1
    assert stats["week"]["short"]["duration"] == "0m45"
    assert stats["week"]["podcast"]["duration"] == "3m00"
    assert stats["week"]["podcast"]["count"] == 1
    assert stats["month"]["video"]["duration"] == "2m30"
    assert stats["month"]["video"]["count"] == 1
    assert stats["month"]["short"]["duration"] == "0m45"
    assert stats["month"]["podcast"]["duration"] == "3m00"
    assert stats["month"]["music"]["duration"] == "9m00"
    assert stats["month"]["music"]["count"] == 2


def test_compact_duration_uses_minute_suffix_without_hours():
    assert formatting.format_compact_duration(613) == "10m13"
    assert formatting.format_compact_duration(7759) == "2h9m19"


def test_two_unit_duration_for_screen_time_rings():
    assert formatting.format_two_unit_duration(120) == "2m"
    assert formatting.format_two_unit_duration(37_800) == "10h30m"
    assert formatting.format_two_unit_duration(180_000) == "2d2h"


def test_dashboard_shows_user_activity_and_logs_keep_technical_statuses():
    db = make_session()
    video = add_video(db)
    video.channel.rating = 3
    short_metadata = Video(
        channel=video.channel,
        yt_video_id="short-metadata",
        title="Short fiche seule",
        url="https://www.youtube.com/shorts/short-metadata",
        media_type="metadata",
        folder_path="/media/short-metadata",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all(
        [
            short_metadata,
            DownloadJob(
                status="played", message="Lecture vidéo", video=video, channel=video.channel
            ),
            DownloadJob(
                status="prompt", message="Prompt envoyé", video=video, channel=video.channel
            ),
            DownloadJob(
                status="downloaded", message="Downloaded", video=video, channel=video.channel
            ),
            DownloadJob(
                status="metadata", message="Imported metadata", video=video, channel=video.channel
            ),
            DownloadJob(status="warning", message="Warning", video=video, channel=video.channel),
        ]
    )
    db.commit()

    dashboard_rendered = site(db).get("/settings").text
    history_rendered = site(db).get("/dashboard/historique").text
    logs_rendered = site(db).get("/logs").text

    assert "Historique" in history_rendered
    assert "Temps de lecture" in dashboard_rendered
    assert "<h3>Global</h3>" in dashboard_rendered
    assert "<h3>Active</h3>" in dashboard_rendered
    assert "Vidéos" in dashboard_rendered
    assert "Shorts" in dashboard_rendered
    assert "<p><span>Fiches</span><strong>2</strong></p>" in dashboard_rendered
    assert "<p><span>Transcripts</span><strong>0</strong></p>" in dashboard_rendered
    assert "<p><span>Chaînes</span><strong>1</strong></p>" in dashboard_rendered
    assert "<p><span>Vidéos</span><strong>1</strong></p>" in dashboard_rendered
    assert "<p><span>Shorts</span><strong>0</strong></p>" in dashboard_rendered
    assert "Stockage" in dashboard_rendered
    assert "5.0 Mo" in dashboard_rendered
    assert ">0m</span>" in dashboard_rendered
    assert "screen-time-track" not in dashboard_rendered
    assert "<th>Action</th>" not in dashboard_rendered
    assert ">played<" not in dashboard_rendered
    assert "Downloaded" in logs_rendered
    assert "Imported metadata" in logs_rendered
    assert "Warning" in logs_rendered


def test_dashboard_media_activity_logs_dedupes_and_respects_limit():
    db = make_session()
    video = add_video(db)
    db.add_all(
        [
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:04 à 0:04: Ancienne position",
                video=video,
                channel=video.channel,
                created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Reprise vidéo pendant 0:11 à 0:11: Position récente",
                video=video,
                channel=video.channel,
                created_at=datetime(2026, 7, 1, 12, 5, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    all_logs = videos_playback.dashboard_media_activity_logs(db)
    limited_logs = videos_playback.dashboard_media_activity_logs(db, limit=0)

    assert len(all_logs) == 1
    assert "0:11" in all_logs[0].message
    assert limited_logs == []


def test_channels_page_shows_rated_channels_by_default():
    db = make_session()
    rated = Channel(url="https://example.test/rated", name="Rated", rating=5)
    unrated = Channel(url="https://example.test/unrated", name="Unrated", rating=0)
    db.add_all([rated, unrated])
    db.commit()

    response = site(db).get("/channels")
    rendered = response.text

    assert "Rated" in rendered
    assert "Unrated" not in rendered
    assert 'name="rated" value="true" type="checkbox" checked' in rendered


def test_channels_page_shows_last_played_activity_without_video_title():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne active", rating=5)
    video = Video(
        channel=channel,
        yt_video_id="active-video",
        title="Titre privé",
        url="https://youtube.com/watch?v=active-video",
        media_type="video",
        folder_path="/media/active-video",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()
    db.add(
        DownloadJob(
            status="played",
            message="Lecture",
            channel_id=channel.id,
            video_id=video.id,
            created_at=datetime(2026, 7, 2, 14, 30, tzinfo=UTC),
        )
    )
    db.commit()

    rendered = site(db).get("/channels").text

    assert "Dernière activité" in rendered
    assert "Jeu. 02 juil. 2026 14:30" in rendered
    assert "Titre privé" not in rendered


def test_channels_page_sorts_by_last_played_activity():
    db = make_session()
    older = Channel(url="https://example.test/older", name="Older", rating=5)
    newer = Channel(url="https://example.test/newer", name="Newer", rating=1)
    inactive = Channel(url="https://example.test/inactive", name="Inactive", rating=5)
    db.add_all([older, newer, inactive])
    db.commit()
    db.add_all(
        [
            DownloadJob(
                status="played",
                message="Lecture",
                channel_id=older.id,
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Lecture",
                channel_id=newer.id,
                created_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    rendered = site(db).get("/channels?sort=activity").text

    assert rendered.index("Newer") < rendered.index("Older")
    assert rendered.index("Older") < rendered.index("Inactive")
    assert '<option value="activity" selected>Dernier média joué</option>' in rendered


def test_channels_page_sorts_by_last_played_activity_by_default():
    db = make_session()
    older = Channel(url="https://example.test/older", name="Older", rating=5)
    newer = Channel(url="https://example.test/newer", name="Newer", rating=1)
    inactive = Channel(url="https://example.test/inactive", name="Inactive", rating=5)
    db.add_all([older, newer, inactive])
    db.commit()
    db.add_all(
        [
            DownloadJob(
                status="played",
                message="Lecture",
                channel_id=older.id,
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            ),
            DownloadJob(
                status="played",
                message="Lecture",
                channel_id=newer.id,
                created_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    rendered = site(db).get("/channels").text

    assert rendered.index("Newer") < rendered.index("Older")
    assert rendered.index("Older") < rendered.index("Inactive")
    assert '<option value="activity" selected>Dernier média joué</option>' in rendered


def test_channels_page_sorts_alphabetically():
    db = make_session()
    beta = Channel(url="https://example.test/beta", name="Beta", rating=5)
    alpha = Channel(url="https://example.test/alpha", name="Alpha", rating=1)
    db.add_all([beta, alpha])
    db.commit()

    rendered = site(db).get("/channels?sort=alpha").text

    assert rendered.index("Alpha") < rendered.index("Beta")
    assert '<option value="alpha" selected>A-Z</option>' in rendered


def test_channels_page_can_show_all_channels():
    db = make_session()
    rated = Channel(url="https://example.test/rated", name="Rated", rating=5)
    unrated = Channel(url="https://example.test/unrated", name="Unrated", rating=0)
    db.add_all([rated, unrated])
    db.commit()

    response = site(db).get("/channels?rated=false")
    rendered = response.text

    assert "Rated" in rendered
    assert "Unrated" in rendered
    assert 'name="rated" value="true" type="checkbox" checked' not in rendered


def test_channels_page_searches_visible_channels():
    db = make_session()
    rated = Channel(
        url="https://example.test/rated", name="Rated", rating=5, category_labels="maker"
    )
    unrated = Channel(
        url="https://example.test/cinema", name="Cinema", rating=0, category_labels="film"
    )
    db.add_all([rated, unrated])
    db.commit()

    rated_rendered = site(db).get("/channels?q=maker").text

    assert "Rated" in rated_rendered
    assert "Cinema" not in rated_rendered
    assert 'name="q" type="search" value="maker"' in rated_rendered

    all_rendered = site(db).get("/channels?rated=false&q=cinema").text

    assert "Cinema" in all_rendered
    assert "Rated" not in all_rendered
    assert 'name="q" type="search" value="cinema"' in all_rendered
    assert 'name="next" value="/channels?rated=false&amp;q=cinema"' in all_rendered


def test_channels_page_search_ignores_accents_and_ranks_names_first():
    db = make_session()
    by_label = Channel(
        url="https://example.test/a", name="Alpha", rating=0, category_labels="cinéma"
    )
    by_name = Channel(url="https://example.test/z", name="Zoom Cinéma", rating=0)
    db.add_all([by_label, by_name])
    db.commit()

    rendered = site(db).get("/channels?rated=false&sort=alpha&q=CINEMA").text
    frame = rendered[
        rendered.index('<turbo-frame id="channel-results"') : rendered.index("</turbo-frame>")
    ]

    # A-Z would put "Alpha" first; the name match outranks the label match.
    assert frame.index("Zoom Cinéma") < frame.index("Alpha")
    assert 'data-live-search="channel-results"' in rendered


def test_channel_categories_form_saves_defaults_and_updates_uncategorized_videos():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test", rating=5)
    empty_video = Video(
        channel=channel,
        yt_video_id="empty-video",
        title="Sans catégorie",
        url="https://youtube.com/watch?v=empty-video",
        media_type="metadata",
        folder_path="/media/empty-video",
        transcript_status=TranscriptStatus.missing,
    )
    custom_video = Video(
        channel=channel,
        yt_video_id="custom-video",
        title="Déjà catégorisée",
        url="https://youtube.com/watch?v=custom-video",
        media_type="metadata",
        folder_path="/media/custom-video",
        category_labels="cuisine",
        transcript_status=TranscriptStatus.missing,
    )
    db.add_all([channel, empty_video, custom_video])
    db.commit()

    response = post_form(
        db,
        f"/channels/{channel.id}/categories",
        {
            "preset_categories": ["maker"],
            "custom_categories": "Science, maker",
            "next": "/channels",
        },
    )

    assert response.headers["location"] == "/channels"
    assert channel.category_labels == "maker,science"
    assert empty_video.category_labels == "maker,science"
    assert custom_video.category_labels == "cuisine"
    assert "science" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_channels_page_renders_channel_category_picker_and_badges():
    db = make_session()
    channel = Channel(
        url="https://example.test/channel", name="Chaîne test", rating=5, category_labels="maker"
    )
    db.add(channel)
    db.commit()

    response = site(db).get("/channels")
    rendered = response.text

    assert 'class="download-form channel-create-form" action="/channels" method="post"' in rendered
    assert 'name="preset_categories" type="checkbox" value="maker"' in rendered
    assert f'action="/channels/{channel.id}/categories"' not in rendered
    assert (
        rendered.count(
            '<span class="category-label" style="--category-bg: #2563eb; --category-border: #2563eb; --category-text: #ffffff;">maker</span>'
        )
        == 2
    )


def test_channel_rating_updates_channel_and_returns_to_filter():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test", rating=5)
    db.add(channel)
    db.commit()

    response = post_form(
        db, f"/channels/{channel.id}/rating", {"rating": "2", "next": "/channels?rated=true"}
    )

    assert channel.rating == 2
    assert response.headers["location"] == "/channels?rated=true"


def test_rating_forms_hand_the_stars_to_the_api():
    # app.js saves a note with PUT {rating} on data-rating-url; `action` stays the no-JS fallback.
    for template in ("_macros.html", "channels.html", "channel_videos.html", "video_detail.html"):
        source = (pathlib.Path("front/templates") / template).read_text(encoding="utf-8")
        for form in re.findall(r'<form class="rating-control[^>]*>', source):
            action = re.search(r'action="([^"]+)"', form).group(1)
            assert f'data-rating-url="/api{action}"' in form, form


def test_base_layout_keeps_scroll_position_on_page_refresh():
    # Without this meta a form that redirects to its own page scrolls back to
    # the top; app.js relies on it (see the turbo:before-fetch-response hook).
    source = pathlib.Path("front/templates/base.html").read_text(encoding="utf-8")
    assert '<meta name="turbo-refresh-scroll" content="preserve">' in source


def test_rating_forms_opt_out_of_turbo_navigation():
    # The stars are repainted in place by app.js; a Turbo submission would
    # follow the redirect and reload the whole page on top of it.
    for template in ("_macros.html", "channels.html", "channel_videos.html", "video_detail.html"):
        source = (pathlib.Path("front/templates") / template).read_text(encoding="utf-8")
        forms = re.findall(r'<form class="rating-control[^>]*>', source)
        assert forms, template
        assert all('data-turbo="false"' in form for form in forms), template


def test_new_channels_are_rated_by_default(monkeypatch, no_profile_backfill):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda url: {"name": "Nouvelle chaîne", "yt_channel_id": "UC123"},
    )

    response = post_form(db, "/channels", {"url": "https://example.test/channel"})
    channel = db.scalar(select(Channel).where(Channel.url == "https://example.test/channel"))

    assert response.headers["location"] == f"/channels?sort=added&added_channel_id={channel.id}"
    assert channel is not None
    assert channel.rating == 1


def channels_page(db, query: str = "") -> str:
    return site(db).get(f"/channels?{query}" if query else "/channels").text


def test_channels_page_shows_added_channel_toast_with_link():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Nouvelle chaîne", rating=1)
    db.add(channel)
    db.commit()

    rendered = channels_page(db, f"added_channel_id={channel.id}&sort=alpha")

    assert "data-toast" in rendered
    assert "Chaîne <strong>Nouvelle chaîne</strong> ajoutée." in rendered
    assert (
        f'<a class="toast-link" href="/videos?channel_id={channel.id}">Voir la chaîne</a>'
        in rendered
    )
    # Le paramètre déclencheur ne doit pas fuiter dans les `next` de la page.
    assert 'name="next" value="/channels?sort=alpha"' in rendered


def test_channels_page_ignores_unknown_added_channel_id():
    db = make_session()
    db.add(Channel(url="https://example.test/channel", name="Nouvelle chaîne", rating=1))
    db.commit()

    for query in ("", "added_channel_id=9999", "added_channel_id=abc"):
        rendered = channels_page(db, query)
        assert "data-toast" not in rendered


def test_redirect_message_is_rendered_as_a_toast_not_an_inline_notice():
    db = make_session()
    db.add(Channel(url="https://example.test/channel", name="Léo Duff", rating=1))
    db.commit()

    message = "25 fiches vidéos importées pour Léo Duff."
    rendered = channels_page(db, urlencode({"message": message}))

    assert f'<p class="toast-text">{message}</p>' in rendered
    assert 'class="toast" role="status" data-toast data-toast-param="message level"' in rendered
    assert 'class="notice' not in rendered


def test_redirect_error_message_is_rendered_as_an_error_toast():
    db = make_session()

    rendered = channels_page(db, urlencode({"level": "error", "message": "Import impossible."}))

    assert (
        'class="toast error" role="alert" data-toast data-toast-param="message level"' in rendered
    )
    assert '<p class="toast-text">Import impossible.</p>' in rendered


def test_redirect_messages_are_rendered_by_the_base_layout_only():
    # A page that renders `message` itself would show it twice, and away from
    # the toast stack.
    for template in pathlib.Path("front/templates").glob("*.html"):
        if template.name == "base.html":
            continue
        assert "{% if message %}" not in template.read_text(encoding="utf-8"), template.name


def test_add_channel_with_a_name_shows_youtube_candidates_instead_of_guessing(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda value: pytest.fail("must not resolve a name"),
    )

    response = post_form(db, "/channels", {"url": "Léo Duff", "preset_categories": ["tech"]})

    assert (
        response.headers["location"] == "/channels?youtube_q=L%C3%A9o+Duff&youtube_categories=tech"
    )
    assert db.scalar(select(Channel)) is None


def youtube_candidate(
    yt_channel_id="UCleo", name="Léo Duff", handle="@LeoDuff", subscriber_count=822000
):
    return {
        "yt_channel_id": yt_channel_id,
        "name": name,
        "handle": handle,
        "url": f"https://www.youtube.com/{handle}",
        "subscriber_count": subscriber_count,
        "description": "High-tech",
        "thumbnail_url": "https://yt3.example/avatar.jpg",
    }


def test_channels_page_lists_youtube_candidates_and_flags_known_channels(monkeypatch):
    db = make_session()
    known = Channel(
        url="https://www.youtube.com/channel/UCknown",
        name="Leo Duff",
        yt_channel_id="UCknown",
        rating=1,
    )
    db.add(known)
    db.commit()
    monkeypatch.setattr(
        channel_listing,
        "search_channels",
        lambda query: [
            youtube_candidate(),
            youtube_candidate("UCknown", "Leo Duff", "@LeFohShow", 341),
        ],
    )

    rendered = channels_page(db, "youtube_q=Léo Duff&youtube_categories=tech&sort=alpha")

    assert "@LeoDuff · 822 000 abonnés" in rendered
    assert '<input type="hidden" name="url" value="https://www.youtube.com/@LeoDuff">' in rendered
    assert '<input type="hidden" name="custom_categories" value="tech">' in rendered
    assert (
        f'<a class="csv-import-badge" href="/videos?channel_id={known.id}">Déjà ajoutée</a>'
        in rendered
    )
    assert rendered.count('name="url" value="https://www.youtube.com/@') == 1
    # The search must not be replayed when another action returns to the page.
    assert 'name="next" value="/channels?sort=alpha"' in rendered


def test_channels_page_reports_a_failed_youtube_search(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_listing,
        "search_channels",
        lambda query: (_ for _ in ()).throw(RuntimeError("réseau")),
    )

    rendered = channels_page(db, "youtube_q=test")

    assert "Recherche YouTube impossible : réseau" in rendered


def test_add_channel_refuses_a_channel_already_in_the_library(monkeypatch, no_profile_backfill):
    db = make_session()
    db.add(
        Channel(
            url="https://www.youtube.com/channel/UC123",
            name="Déjà là",
            yt_channel_id="UC123",
            rating=1,
        )
    )
    db.commit()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda value: {
            "url": "https://www.youtube.com/@deja-la",
            "name": "Déjà là",
            "yt_channel_id": "UC123",
        },
    )

    response = post_form(db, "/channels", {"url": "@deja-la"})

    assert "level=error" in response.headers["location"]
    assert db.query(Channel).count() == 1


def test_free_text_channel_name_is_not_resolved_by_guessing():
    with pytest.raises(ChannelNotFoundError):
        resolve_channel_url("Léo Duff")


def test_search_channels_reads_the_channel_filtered_youtube_search(monkeypatch):
    requested = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            requested["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            requested["url"] = url
            return {
                "entries": [
                    {
                        "id": "UCleo",
                        "channel": "Léo Duff",
                        "uploader_id": "@LeoDuff",
                        "channel_follower_count": 822000,
                        "description": " High-tech ",
                        "thumbnails": [{"url": "//yt3.example/avatar.jpg"}],
                    },
                    {"id": "UCnohandle", "title": "Sans handle"},
                    {"id": "dQw4w9WgXcQ", "title": "Une vidéo"},
                    None,
                ]
            }

    monkeypatch.setattr(channel_info, "YoutubeDL", FakeYoutubeDL)

    results = channel_info.search_channels("Léo Duff", limit=5)

    assert (
        requested["url"]
        == "https://www.youtube.com/results?search_query=L%C3%A9o+Duff&sp=EgIQAg%3D%3D"
    )
    assert requested["opts"]["playlistend"] == 5
    assert results == [
        {
            "yt_channel_id": "UCleo",
            "name": "Léo Duff",
            "handle": "@LeoDuff",
            "url": "https://www.youtube.com/@LeoDuff",
            "subscriber_count": 822000,
            "description": "High-tech",
            "thumbnail_url": "https://yt3.example/avatar.jpg",
        },
        {
            "yt_channel_id": "UCnohandle",
            "name": "Sans handle",
            "handle": None,
            "url": "https://www.youtube.com/channel/UCnohandle",
            "subscriber_count": None,
            "description": None,
            "thumbnail_url": None,
        },
    ]
    assert channel_info.search_channels("   ") == []


def test_channel_handle_resolves_to_exact_handle_url():
    assert resolve_channel_url("@exact-handle") == "https://www.youtube.com/@exact-handle"


def test_bare_channel_handle_resolves_to_exact_handle_url():
    assert resolve_channel_url("Quelle-Histoire") == "https://www.youtube.com/@Quelle-Histoire"


def test_imported_video_channel_name_does_not_fall_back_to_channel_id():
    name, url, yt_channel_id = channel_values_from_info(
        {
            "channel": "UCoejzfiaEjCusdpdX9W8jBQ",
            "channel_id": "UCoejzfiaEjCusdpdX9W8jBQ",
            "channel_url": "https://www.youtube.com/@Quelle-Histoire",
        }
    )

    assert name == "Quelle-Histoire"
    assert url == "https://www.youtube.com/@Quelle-Histoire"
    assert yt_channel_id == "UCoejzfiaEjCusdpdX9W8jBQ"


def test_add_channel_returns_not_found_for_missing_handle(monkeypatch, no_profile_backfill):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda channel_input: (_ for _ in ()).throw(
            ChannelNotFoundError("Chaîne introuvable pour @missing-handle")
        ),
    )

    response = post_form(db, "/channels", {"url": "@missing-handle"})

    assert response.status_code == 404
    # The form answers like `POST /api/channels`: the service's French message.
    assert response.json()["detail"] == "Chaîne introuvable pour @missing-handle"


def test_api_create_channel_saves_resolved_url_from_name(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda channel_input: {
            "url": "https://www.youtube.com/@api-channel",
            "name": "Chaîne API",
            "yt_channel_id": "UCAPI",
        },
    )

    # A free-text name is refused by `ChannelCreate` (it goes through the YouTube search);
    # a handle is resolved, and the URL YouTube gives back is the one saved.
    channel = api_channels.create_channel(
        api_channels.ChannelCreate(url="@api-channel"), BackgroundTasks(), db
    )

    assert channel.name == "Chaîne API"
    assert channel.url == "https://www.youtube.com/@api-channel"


def test_api_create_channel_refuses_a_channel_added_under_another_url(monkeypatch):
    # Same rule as the HTML form: the YouTube id identifies the channel, not the URL.
    db = make_session()
    db.add(
        Channel(
            url="https://www.youtube.com/channel/UCAPI", name="Chaîne API", yt_channel_id="UCAPI"
        )
    )
    db.commit()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda channel_input: {
            "url": "https://www.youtube.com/@api-channel",
            "name": "Chaîne API",
            "yt_channel_id": "UCAPI",
        },
    )

    with pytest.raises(HTTPException) as exc:
        api_channels.create_channel(
            api_channels.ChannelCreate(url="@api-channel"), BackgroundTasks(), db
        )

    assert exc.value.status_code == 409
    assert db.scalar(select(func.count(Channel.id))) == 1


def test_api_and_form_delete_a_channel_with_its_profile_files(monkeypatch):
    removed = []
    monkeypatch.setattr(
        channel_manage,
        "remove_channel_profile_files",
        lambda media_root, yt_channel_id: removed.append(yt_channel_id),
    )
    db = make_session()
    first = Channel(url="https://example.test/a", name="A", yt_channel_id="UCA")
    second = Channel(url="https://example.test/b", name="B", yt_channel_id="UCB")
    db.add_all([first, second])
    db.commit()

    api_channels.delete_channel(first.id, db)
    post_form(db, f"/channels/{second.id}/delete", {"next": "/channels"})

    assert removed == ["UCA", "UCB"]
    assert db.scalar(select(func.count(Channel.id))) == 0


def test_api_create_channel_returns_not_found_for_missing_handle(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda channel_input: (_ for _ in ()).throw(
            ChannelNotFoundError("Chaîne introuvable pour @missing-handle")
        ),
    )

    with pytest.raises(HTTPException) as exc:
        api_channels.create_channel(
            api_channels.ChannelCreate(url="@missing-handle"), BackgroundTasks(), db
        )

    assert exc.value.status_code == 404
    # The service's French message reaches the client, as on the HTML form.
    assert exc.value.detail == "Chaîne introuvable pour @missing-handle"


def test_add_channel_saves_category_labels(monkeypatch, no_profile_backfill):
    db = make_session()
    monkeypatch.setattr(
        channel_manage,
        "extract_channel_info",
        lambda url: {"name": "Nouvelle chaîne", "yt_channel_id": "UC123"},
    )

    response = post_form(
        db,
        "/channels",
        {
            "url": "https://example.test/channel",
            "preset_categories": ["maker"],
            "custom_categories": "Science, maker",
        },
    )
    channel = db.scalar(select(Channel).where(Channel.url == "https://example.test/channel"))

    assert response.headers["location"] == f"/channels?sort=added&added_channel_id={channel.id}"
    assert channel is not None
    assert channel.category_labels == "maker,science"
    assert "science" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_rating_returns_to_internal_origin_and_rejects_external_redirect():
    db = make_session()
    video = add_video(db)

    url = f"/videos/{video.id}/rating"
    detail_response = post_form(db, url, {"rating": "4", "next": f"/videos/{video.id}"})
    external_response = post_form(
        db, url, {"rating": "3", "next": "https://youtube.com/watch?v=abc123"}
    )

    assert detail_response.headers["location"] == f"/videos/{video.id}"
    assert external_response.headers["location"] == "/videos"


def post_settings(db, media_root, **fields):
    """The no-JS settings form, with the fields a test cares about (quota 2.5 Go by default)."""
    return post_form(db, "/settings", {"media_root": str(media_root), "quota_gb": "2.5", **fields})


def test_settings_form_updates_media_root_and_quota(tmp_path):
    db = make_session()

    response = post_settings(db, tmp_path, video_category_labels="Maker\nScience\nmaker\nHistoire")

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "media_root").value == str(tmp_path)
    assert db.get(AppSetting, "global_quota_bytes").value == str(int(2.5 * 1024 * 1024 * 1024))
    # The plain list is stored as bare labels; their colours are assigned when read.
    assert get_video_category_label_styles(db) == [
        {"label": "maker", "color": "#16a34a"},
        {"label": "science", "color": "#2563eb"},
        {"label": "histoire", "color": "#7c3aed"},
    ]


def test_settings_form_saves_category_label_colors(tmp_path):
    db = make_session()
    category_styles = json.dumps(
        [
            {"label": "Maker", "color": "#ff0066"},
            {"label": "Science", "color": "#112233"},
            {"label": "maker", "color": "#000000"},
        ]
    )

    response = post_settings(db, tmp_path, video_category_styles=category_styles)

    assert response.headers["location"] == "/settings"
    assert json.loads(db.get(AppSetting, "video_category_labels").value) == [
        {"label": "maker", "color": "#ff0066"},
        {"label": "science", "color": "#112233"},
    ]


def test_settings_form_saves_video_library_views(tmp_path):
    db = make_session()
    library_views = json.dumps(
        [
            {
                "name": "Maker notés",
                "asset_filter_mode": "or",
                "category_filter_mode": "and",
                "assets": ["video"],
                "categories": ["Maker", "Science"],
                "excluded_assets": ["shorts"],
                "excluded_categories": ["dessert"],
                "rated": True,
            }
        ]
    )

    response = post_settings(
        db, tmp_path, video_category_labels="Maker\nScience", video_library_views=library_views
    )

    assert response.headers["location"] == "/settings"
    assert json.loads(db.get(AppSetting, "video_library_views").value) == [
        {
            "name": "Maker notés",
            "asset_filter_mode": "or",
            "category_filter_mode": "and",
            "assets": ["video"],
            "categories": ["maker", "science"],
            "excluded_assets": ["shorts"],
            "excluded_categories": ["dessert"],
            "rated": True,
        }
    ]


def test_settings_page_renders_custom_category_labels(tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="global_quota_bytes", value=str(2 * 1024 * 1024 * 1024)))
    db.add(
        AppSetting(
            key="video_category_labels",
            value=json.dumps(
                [
                    {"label": "maker", "color": "#ff0066"},
                    {"label": "science", "color": "#112233"},
                    {"label": "histoire", "color": "#2563eb"},
                ]
            ),
        )
    )
    db.commit()

    response = site(db).get("/settings")
    rendered = response.text

    assert "Labels de catégories vidéo" in rendered
    assert "data-initial-labels=" in rendered
    assert "#ff0066" in rendered
    assert "#112233" in rendered
    assert "histoire" in rendered
    assert 'data-category-new-color type="color"' in rendered
    assert "Sous-bibliothèques" in rendered
    assert "data-initial-views=" in rendered
    # Summary tiles and the collapsed rarely-used blocks.
    assert 'class="settings-stats"' in rendered
    assert 'class="settings-fold settings-fold-card"' in rendered
    assert "data-settings-nav" in rendered
    assert 'href="/logs"' in rendered


def test_settings_page_renders_no_progress_category_checkboxes(tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="global_quota_bytes", value=str(2 * 1024 * 1024 * 1024)))
    db.add(
        AppSetting(
            key="video_category_labels",
            value=json.dumps(
                [
                    {"label": "maker", "color": "#ff0066"},
                    {"label": "musique", "color": "#112233"},
                ]
            ),
        )
    )
    db.commit()

    response = site(db).get("/settings")
    rendered = response.text

    assert "Catégories sans barre de progression" in rendered
    assert 'value="maker"' in rendered
    assert 'name="no_progress_categories" value="musique" checked' in rendered
    # "amv" is a default selection but isn't a registered category label here,
    # so it still surfaces as a (checked, uncolored) option instead of vanishing.
    assert 'name="no_progress_categories" value="amv" checked' in rendered


def test_ensure_default_settings_seeds_defaults_without_llm_provider():
    from back.services.common.settings import ensure_default_settings

    db = make_session()

    ensure_default_settings(db)

    assert db.get(AppSetting, "media_root") is not None
    assert db.get(AppSetting, "llm_provider") is None


def test_settings_form_saves_no_progress_categories(tmp_path):
    db = make_session()

    response = post_settings(db, tmp_path, no_progress_categories=["musique"])

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "no_progress_category_labels").value == "musique"


def test_settings_form_saves_sponsor_segment_categories(tmp_path):
    db = make_session()

    response = post_settings(db, tmp_path, sponsor_segment_categories=["sponsor", "intro"])

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "sponsor_segment_categories").value == "sponsor,intro"


def test_settings_page_renders_sponsor_segment_category_checkboxes(tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="global_quota_bytes", value=str(2 * 1024 * 1024 * 1024)))
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,outro"))
    db.commit()

    response = site(db).get("/settings")
    rendered = response.text

    assert "Segments sponsorisés" in rendered
    assert 'name="sponsor_segment_categories" value="sponsor" checked' in rendered
    assert 'name="sponsor_segment_categories" value="outro" checked' in rendered
    assert 'name="sponsor_segment_categories" value="selfpromo">' in rendered  # present, unchecked


def test_get_sponsor_segment_categories_defaults_to_all():
    from back.services.common.settings import (
        SPONSOR_SEGMENT_CATEGORY_CHOICES,
        get_sponsor_segment_categories,
    )

    db = make_session()
    assert get_sponsor_segment_categories(db) == SPONSOR_SEGMENT_CATEGORY_CHOICES


def test_get_sponsor_segment_categories_filters_unknown_values():
    from back.services.common.settings import get_sponsor_segment_categories

    db = make_session()
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,bogus,outro"))
    db.commit()
    assert get_sponsor_segment_categories(db) == ["sponsor", "outro"]


def test_get_sponsor_skip_enabled_defaults_to_true():
    db = make_session()

    assert get_sponsor_skip_enabled(db) is True


def test_get_sponsor_skip_enabled_reads_stored_value():
    db = make_session()
    db.add(AppSetting(key="sponsor_skip_enabled", value="false"))
    db.commit()

    assert get_sponsor_skip_enabled(db) is False


def test_settings_form_persists_sponsor_skip_enabled(tmp_path):
    db = make_session()

    post_settings(db, tmp_path, quota_gb="10.0", sponsor_skip_enabled="on")
    assert get_sponsor_skip_enabled(db) is True

    post_settings(db, tmp_path, quota_gb="10.0", sponsor_skip_enabled="")
    assert get_sponsor_skip_enabled(db) is False


def test_settings_page_shows_llm_usage_costs(tmp_path):
    db = make_session()
    db.add(
        LlmJob(
            kind="notes",
            provider="anthropic",
            video_id=None,
            prompt="p",
            status="applied",
            model="claude-haiku-4-5",
            input_tokens=1000,
            output_tokens=200,
            cost_usd=0.002,
        )
    )
    db.commit()

    response = site(db).get("/settings")
    rendered = response.text

    assert "Coûts LLM" in rendered
    assert "Notes structurées" in rendered
    assert "$0.0020" in rendered


def test_settings_page_shows_never_scanned_when_no_auto_scan_recorded(tmp_path):
    db = make_session()

    response = site(db).get("/settings")
    rendered = response.text

    assert "Suivi automatique" in rendered
    assert "Aucun scan automatique n'a encore tourné." in rendered


def test_settings_page_shows_last_auto_scan_result(tmp_path):
    db = make_session()
    record_scan_result(db, {"status": "completed", "downloaded": 5, "deleted": 0})

    response = site(db).get("/settings")
    rendered = response.text

    assert "Dernier scan :" in rendered
    assert "5 nouvelles fiches importées." in rendered


def test_videos_page_uses_custom_category_options_from_settings(monkeypatch):
    db = make_session()
    db.add(
        AppSetting(
            key="video_category_labels",
            value=json.dumps(
                [
                    {"label": "histoire", "color": "#ff0066"},
                    {"label": "interview", "color": "#112233"},
                ]
            ),
        )
    )
    db.commit()
    video = add_video(db)

    response = site(db).get("/videos")
    rendered = response.text

    assert video.title in rendered
    assert 'name="category" type="checkbox" value="histoire"' in rendered
    assert 'name="category" type="checkbox" value="interview"' in rendered
    assert "--category-bg: #ff0066;" in rendered
    assert "--category-bg: #112233;" in rendered
    assert 'name="category" type="checkbox" value="cuisine"' not in rendered


def test_settings_api_updates_media_root_and_quota(tmp_path):
    db = make_session()

    result = api_settings.update_settings(
        SettingsUpdate(
            media_root=str(tmp_path),
            global_quota_bytes=100,
            video_category_labels=["Maker", "Science", "maker"],
        ),
        db,
    )

    assert result.media_root == str(tmp_path)
    assert result.global_quota_bytes == 100
    assert result.video_category_labels == ["maker", "science"]
    assert result.video_category_label_styles == [
        {"label": "maker", "color": "#16a34a"},
        {"label": "science", "color": "#2563eb"},
    ]
    assert db.get(AppSetting, "media_root").value == str(tmp_path)
    assert db.get(AppSetting, "global_quota_bytes").value == "100"
    assert db.get(AppSetting, "video_category_labels").value == "maker,science"


def test_settings_api_updates_category_label_colors(tmp_path):
    db = make_session()

    result = api_settings.update_settings(
        SettingsUpdate(
            media_root=str(tmp_path),
            global_quota_bytes=100,
            video_category_label_styles=[
                {"label": "Maker", "color": "#ff0066"},
                {"label": "Science", "color": "#112233"},
            ],
        ),
        db,
    )

    assert result.video_category_labels == ["maker", "science"]
    assert result.video_category_label_styles == [
        {"label": "maker", "color": "#ff0066"},
        {"label": "science", "color": "#112233"},
    ]
    assert json.loads(db.get(AppSetting, "video_category_labels").value) == [
        {"label": "maker", "color": "#ff0066"},
        {"label": "science", "color": "#112233"},
    ]


def test_settings_api_updates_video_library_views(tmp_path):
    db = make_session()

    result = api_settings.update_settings(
        SettingsUpdate(
            video_library_views=[
                {
                    "name": "Podcasts",
                    "asset_filter_mode": "or",
                    "category_filter_mode": "or",
                    "assets": ["video"],
                    "categories": ["Podcasts"],
                    "excluded_assets": ["shorts"],
                    "excluded_categories": ["clips"],
                    "rated": False,
                }
            ],
        ),
        db,
    )

    assert result.video_library_views == [
        {
            "name": "Podcasts",
            "asset_filter_mode": "or",
            "category_filter_mode": "or",
            "assets": ["video"],
            "categories": ["podcasts"],
            "excluded_assets": ["shorts"],
            "excluded_categories": ["clips"],
            "rated": False,
        }
    ]
    assert json.loads(db.get(AppSetting, "video_library_views").value) == result.video_library_views


def test_video_list_state_follows_playback_when_unset():
    video = Video(
        yt_video_id="ls-auto",
        title="Auto",
        url="https://youtube.com/watch?v=ls-auto",
        folder_path="/media/ls-auto",
    )

    assert videos_list_state.video_list_state(video, {"is_completed": True}, False) == "watched"
    assert videos_list_state.video_list_state(video, {"is_completed": False}, False) == "normal"
    assert videos_list_state.video_list_state(video, None, False) == "normal"


def test_video_list_state_ignores_playback_for_replay_categories():
    video = Video(
        yt_video_id="ls-replay",
        title="Replay",
        url="https://youtube.com/watch?v=ls-replay",
        folder_path="/media/ls-replay",
    )

    assert videos_list_state.video_list_state(video, {"is_completed": True}, True) == "normal"


def test_video_list_state_honours_manual_watched_even_on_replay_category():
    video = Video(
        yt_video_id="ls-manual",
        title="Manuel",
        url="https://youtube.com/watch?v=ls-manual",
        folder_path="/media/ls-manual",
        list_state="watched",
    )

    assert videos_list_state.video_list_state(video, None, True) == "watched"


def test_video_list_state_unwatched_cancels_completed_playback():
    video = Video(
        yt_video_id="ls-unwatched",
        title="Non lu",
        url="https://youtube.com/watch?v=ls-unwatched",
        folder_path="/media/ls-unwatched",
        list_state="unwatched",
    )

    assert videos_list_state.video_list_state(video, {"is_completed": True}, False) == "normal"


def test_video_list_state_hidden_wins_over_playback():
    video = Video(
        yt_video_id="ls-hidden",
        title="Écartée",
        url="https://youtube.com/watch?v=ls-hidden",
        folder_path="/media/ls-hidden",
        list_state="hidden",
    )

    assert videos_list_state.video_list_state(video, {"is_completed": False}, False) == "hidden"


def test_set_video_list_state_persists_each_value():
    db = make_session()
    video = add_video(db)

    for state in ("watched", "unwatched", "hidden"):
        videos_editing.set_video_list_state(db, video, state)
        assert db.get(Video, video.id).list_state == state


def test_set_video_list_state_clear_resets_to_null():
    db = make_session()
    video = add_video(db)
    videos_editing.set_video_list_state(db, video, "hidden")

    videos_editing.set_video_list_state(db, video, "clear")

    assert db.get(Video, video.id).list_state is None


def test_set_video_list_state_rejects_unknown_value():
    db = make_session()
    video = add_video(db)

    with pytest.raises(ValueError, match="État de liste inconnu."):
        videos_editing.set_video_list_state(db, video, "bogus")


def test_videos_page_hide_hidden_excludes_only_hidden_videos():
    db = make_session()
    kept = add_video(db)
    channel = kept.channel
    hidden = Video(
        channel=channel,
        yt_video_id="hidden123",
        title="Vidéo écartée",
        url="https://youtube.com/watch?v=hidden123",
        media_type="video",
        folder_path="/media/hidden",
        video_path="/media/hidden/video.mp4",
        transcript_status=TranscriptStatus.missing,
        list_state="hidden",
    )
    marked_watched = Video(
        channel=channel,
        yt_video_id="watched123",
        title="Vidéo marquée lue",
        url="https://youtube.com/watch?v=watched123",
        media_type="video",
        folder_path="/media/watched",
        video_path="/media/watched/video.mp4",
        transcript_status=TranscriptStatus.missing,
        list_state="watched",
    )
    db.add_all([hidden, marked_watched])
    db.commit()

    rendered = site(db).get("/videos?hide_hidden=1").text

    assert kept.title in rendered
    assert marked_watched.title in rendered
    assert hidden.title not in rendered
    assert 'name="hide_hidden" type="checkbox" value="1" checked' in rendered


def test_videos_page_without_hide_hidden_keeps_hidden_videos():
    db = make_session()
    add_video(db)
    hidden = Video(
        yt_video_id="hidden456",
        title="Vidéo écartée visible",
        url="https://youtube.com/watch?v=hidden456",
        media_type="video",
        folder_path="/media/hidden456",
        video_path="/media/hidden456/video.mp4",
        transcript_status=TranscriptStatus.missing,
        list_state="hidden",
    )
    db.add(hidden)
    db.commit()

    rendered = site(db).get("/videos").text

    assert hidden.title in rendered
    assert 'class="video-row video-row-hidden"' in rendered


def test_video_card_renders_list_state_buttons():
    db = make_session()
    video = add_video(db)
    video.list_state = "watched"
    db.commit()

    rendered = site(db).get("/videos").text

    assert f'data-list-state-toggle data-video-id="{video.id}"' in rendered
    assert 'data-list-state-target="watched"' in rendered
    assert 'data-list-state-target="hidden"' in rendered
    assert 'class="video-row video-row-watched"' in rendered
    assert "list-state-toggle-active" in rendered


def test_video_auto_list_state_reflects_playback_only():
    assert videos_list_state.video_auto_list_state({"is_completed": True}, False) == "watched"
    assert videos_list_state.video_auto_list_state({"is_completed": True}, True) == "normal"
    assert videos_list_state.video_auto_list_state({"is_completed": False}, False) == "normal"
    assert videos_list_state.video_auto_list_state(None, False) == "normal"


def test_video_card_exposes_auto_list_state_for_unhiding():
    db = make_session()
    video = add_video(db)
    video.list_state = "hidden"
    db.commit()
    db.add(
        DownloadJob(
            video_id=video.id,
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Lecture",
                    "media_label": "vidéo",
                    "position_seconds": 600,
                    "duration_seconds": 600,
                    "watched_seconds": 600,
                }
            ),
        )
    )
    db.commit()

    rendered = site(db).get("/videos").text

    assert 'data-list-state="hidden" data-list-state-auto="watched"' in rendered


def test_list_state_buttons_are_icon_only_with_accessible_labels():
    db = make_session()
    add_video(db)

    rendered = site(db).get("/videos").text

    assert 'aria-label="Marquer comme vu"' in rendered
    assert 'aria-label="Écarter cette vidéo"' in rendered
    assert "list-state-icon" in rendered
    assert ">Lu</button>" not in rendered
    assert ">Écartée</button>" not in rendered


def add_playback_job(db, video, position=5, duration=600):
    db.add(
        DownloadJob(
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Reprise",
                    "media_label": "vidéo",
                    "position_seconds": position,
                    "duration_seconds": duration,
                    "watched_seconds": position,
                }
            ),
            video=video,
            channel=video.channel if video else None,
            created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()


def test_resume_page_renders_list_state_buttons():
    db = make_session()
    video = add_video(db)
    add_playback_job(db, video)

    rendered = site(db).get("/dashboard/historique").text

    assert f'data-list-state-toggle data-video-id="{video.id}"' in rendered
    assert 'aria-label="Marquer comme vu"' in rendered
    assert 'aria-label="Écarter cette vidéo"' in rendered


def test_resume_page_greys_hidden_video_more_strongly():
    db = make_session()
    video = add_video(db)
    video.list_state = "hidden"
    db.commit()
    add_playback_job(db, video)

    rendered = site(db).get("/dashboard/historique").text

    assert 'class="dashboard-media-row video-card dashboard-media-row-hidden"' in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' not in rendered


def test_resume_page_greys_manually_watched_video():
    db = make_session()
    video = add_video(db)
    video.list_state = "watched"
    db.commit()
    add_playback_job(db, video)

    rendered = site(db).get("/dashboard/historique").text

    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-hidden"' not in rendered


def test_resume_page_has_no_list_state_buttons_without_a_video():
    db = make_session()
    add_playback_job(db, None)

    rendered = site(db).get("/dashboard/historique").text

    assert "data-list-state-toggle" not in rendered


def test_css_hides_progress_bar_inside_watched_and_hidden_rows():
    """Le serveur omet deja la barre quand la video est lue ; ces regles couvrent
    la bascule cote client, ou la ligne change de classe sans rechargement."""
    css = (
        pathlib.Path(__file__).resolve().parent.parent
        / "front"
        / "static"
        / "css"
        / "tailwind.input.css"
    ).read_text(encoding="utf-8")

    for row_class in (
        "video-row-watched",
        "video-row-hidden",
        "dashboard-media-row-completed",
        "dashboard-media-row-hidden",
    ):
        assert f".{row_class} .video-card-progress" in css


def test_css_hides_topbar_on_phone():
    """Sur telephone la barre du haut (titre Raton seul) est masquee ; la
    hauteur du chat de l'accueil en tient compte."""
    css = (
        pathlib.Path(__file__).resolve().parent.parent
        / "front"
        / "static"
        / "css"
        / "tailwind.input.css"
    ).read_text(encoding="utf-8")
    phone_blocks = re.findall(r"@media \(max-width: 800px\) \{\n(.*?)\n\}\n", css, flags=re.S)

    assert any(
        re.search(r"\n  \.topbar \{\n    display: none;", "\n" + block) for block in phone_blocks
    )
    assert any(
        re.search(r"body\.has-mini-player \{\n    --home-mini-reserve: 180px;", "\n" + block)
        for block in phone_blocks
    )
    assert any(
        re.search(r"main:has\(\.dashboard-home\) \{\n    padding-bottom: 0;", "\n" + block)
        for block in phone_blocks
    )
    assert any(
        "100dvh - 90px - var(--home-mini-reserve, 0px) - env(safe-area-inset-bottom)" in block
        for block in phone_blocks
    )


def test_video_detail_explains_purged_media():
    db = make_session()
    video = add_video(db)
    video.video_path = None
    video.watched_at = datetime(2026, 6, 3, tzinfo=UTC)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert "retirés automatiquement du serveur" in rendered


def test_video_detail_has_no_purge_message_for_archived_video():
    db = make_session()
    video = add_video(db)
    video.video_path = None
    video.watched_at = datetime(2026, 6, 3, tzinfo=UTC)
    video.rating = 5
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert "retirés automatiquement du serveur" not in rendered


def test_video_detail_wraps_players_in_media_pager():
    db = make_session()
    video = Video(
        yt_video_id="pager123",
        title="Carrousel",
        url="https://youtube.com/watch?v=pager123",
        media_type="video",
        folder_path="/tmp/does-not-matter",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert "data-media-pager" in rendered
    assert 'data-initial="video"' in rendered
    # Nothing downloaded yet: both slides offer their download button.
    assert 'data-media-slide="video" data-state="idle"' in rendered
    assert 'data-media-slide="audio" data-state="idle"' in rendered
    assert rendered.count("data-media-download") == 2
    assert f'data-track-src="/api/videos/{video.id}/audio"' in rendered
    assert rendered.count('data-quality="') >= 7 + 7  # pager picker + action bar popover
    assert len(re.findall(r"data-media-seek[\s>]", rendered)) == 1
    assert 'role="slider"' in rendered
    assert "media-wave-bar" not in rendered
    # Icon toggle under the player (video left, audio right).
    assert re.search(r'data-media-dot="video"[^>]*>\s*<svg', rendered)
    assert re.search(r'data-media-dot="audio"[^>]*>\s*<svg', rendered)
    assert rendered.index('data-media-dot="video"') < rendered.index('data-media-dot="audio"')
    # Phone "more" popover: description, segments and transcript retry.
    assert 'class="video-more"' in rendered
    assert 'data-click-proxy="#transcript-retry-button"' in rendered
    assert rendered.count('id="transcript-retry-button"') == 1
    assert "data-retry-status-mirror" in rendered


def test_video_detail_more_popover_hides_retry_when_transcript_exists(tmp_path):
    db = make_session()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("bonjour", encoding="utf-8")
    video = Video(
        yt_video_id="moretranscript1",
        title="Avec transcript",
        url="https://youtube.com/watch?v=moretranscript1",
        media_type="video",
        folder_path=str(tmp_path),
        transcript_path=str(transcript),
        transcript_status=TranscriptStatus.downloaded,
    )
    db.add(video)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert 'class="video-more"' in rendered
    assert 'type="button" class="secondary" data-click-proxy' not in rendered
    assert "data-retry-status-mirror aria-live" not in rendered
    assert 'id="transcript-retry-button"' not in rendered


def test_video_detail_pager_opens_on_audio_for_audio_only_video():
    db = make_session()
    video = Video(
        yt_video_id="pageraudio1",
        title="Audio seul",
        url="https://youtube.com/watch?v=pageraudio1",
        media_type="audio",
        folder_path="/tmp/does-not-matter",
        audio_path="/tmp/does-not-matter/a.m4a",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert 'data-initial="audio"' in rendered
    assert 'data-media-slide="video" data-state="idle"' in rendered
    assert 'data-media-slide="audio" data-state="ready"' in rendered
    # Both buttons are always in the markup; the slide's data-state shows or hides them.
    assert rendered.count("data-media-download") == 2


def test_video_detail_pager_marks_both_slides_ready_when_formats_coexist():
    db = make_session()
    video = Video(
        yt_video_id="pagerboth1",
        title="Les deux",
        url="https://youtube.com/watch?v=pagerboth1",
        media_type="video",
        folder_path="/tmp/does-not-matter",
        video_path="/tmp/does-not-matter/v.mp4",
        audio_path="/tmp/does-not-matter/a.m4a",
        transcript_status=TranscriptStatus.missing,
    )
    db.add(video)
    db.commit()

    rendered = site(db).get(f"/videos/{video.id}").text

    assert 'data-initial="video"' in rendered
    assert 'data-media-slide="video" data-state="ready"' in rendered
    assert 'data-media-slide="audio" data-state="ready"' in rendered


def test_base_mini_player_is_one_link_to_the_audio_pane():
    base = (
        pathlib.Path(__file__).resolve().parent.parent / "front" / "templates" / "base.html"
    ).read_text()
    start = base.index("data-mini-player-open")
    link = base[start : base.index("</a>", start)]

    for marker in (
        "data-mini-player-thumb",
        "data-mini-player-title",
        "data-mini-player-channel",
        "data-mini-player-meta-time",
    ):
        assert marker in link


def test_share_import_waits_for_the_import_and_returns_the_video_url(monkeypatch):
    db = make_session()
    video = add_video(db)
    calls = []

    def fake_run(job_id, url, media_types, download_transcript):
        calls.append((url, media_types, download_transcript))
        job = db.get(DownloadJob, job_id)
        job.status, job.video_id = "downloaded", video.id
        db.commit()

    monkeypatch.setattr(downloads, "run_manual_download_job", fake_run)

    # The Shortcut reaches the site under the address set on the phone (LAN or WireGuard).
    response = site(db, base_url="http://pt.lan:8000").post(
        "/videos/share-import", data={"url": " https://youtu.be/abc123 "}
    )

    payload = response.json()
    assert response.status_code == 200
    assert calls == [("https://youtu.be/abc123", ["metadata"], True)]
    assert payload["video_id"] == video.id
    assert payload["video_url"] == f"http://pt.lan:8000/videos/{video.id}"


def test_share_import_reports_a_failed_import_and_rejects_other_hosts(monkeypatch):
    db = make_session()

    def fake_run(job_id, *args):
        job = db.get(DownloadJob, job_id)
        job.status, job.message = "failed", "Vidéo indisponible"
        db.commit()

    monkeypatch.setattr(downloads, "run_manual_download_job", fake_run)

    client = site(db)
    failed = client.post("/videos/share-import", data={"url": "https://youtu.be/abc123"})
    rejected = client.post("/videos/share-import", data={"url": "https://evil.test/watch?v=abc123"})

    assert failed.status_code == 502
    assert failed.json()["message"] == "Vidéo indisponible"
    assert rejected.status_code == 400
