import asyncio
import json
import pathlib
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app import main
from app.api import routes as api_routes
from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.llm_job import LlmJob
from app.models.setting import AppSetting
from app.models.video import TranscriptStatus, Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.schemas.settings import SettingsUpdate
from app.services import background_jobs, search
from app.services import yt as yt_service
from app.services.llm import CompletionFailed, CompletionResult, UsageTally
from app.services.scanner import channel_values_from_info
from app.services.scheduler import record_scan_result
from app.services.settings import get_sponsor_skip_enabled
from app.services.yt import ChannelNotFoundError, resolve_channel_url
from app.web import formatting, playback, shared, video_library
from app.web.routes import channels as channels_routes
from app.web.routes import dashboard as dashboard_routes
from app.web.routes import media as media_routes
from app.web.routes import settings as settings_routes
from app.web.routes import transcript as transcript_routes
from app.web.routes import videos as videos_routes


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


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
    template = shared.templates.env.get_template("videos.html")
    video = type(
        "VideoView",
        (),
        {
            "id": 42,
            "title": "Titre local",
            "url": "https://youtube.com/watch?v=abc",
            "media_type": "video",
            "channel": type("ChannelView", (), {"id": 7, "name": "Chaîne locale"})(),
            "published_at": None,
            "transcript_path": "/media/transcript.txt",
            "transcript_status": type("Status", (), {"value": "downloaded"})(),
            "video_path": "/media/video.mp4",
            "audio_path": None,
            "thumbnail_path": "/media/thumbnail.webp",
            "rating": 0,
            "file_size_bytes": 0,
            "list_state": None,
        },
    )()

    rendered = template.render(
        videos=[video],
        video_cards=[
            {
                "downloaded": True,
                "video": video,
                "title": video.title,
                "channel_id": 7,
                "channel_name": "Chaîne locale",
                "published_at": None,
                "media_type": "video",
                "labels": [
                    {"text": "Vidéo", "kind": "video"},
                    {"text": "Métadonnées", "kind": "metadata"},
                    {"text": "Transcript", "kind": "transcript"},
                ],
                "file_size_bytes": 0,
                "view_count": "12 345",
                "duration": "2:03",
                "transcript_path": video.transcript_path,
                "transcript_status": video.transcript_status,
                "video_path": video.video_path,
                "audio_path": video.audio_path,
                "thumbnail_path": video.thumbnail_path,
            }
        ],
        channels=[],
        selected_channel=None,
        selected_channel_id=None,
        selected_channel_section=None,
        asset_filter_options=[
            {"text": "Vidéo", "kind": "video"},
            {"text": "Métadonnées", "kind": "metadata"},
            {"text": "Transcript", "kind": "transcript"},
            {"text": "Audio", "kind": "audio"},
        ],
        selected_asset_filters={"audio", "video"},
        selected_excluded_asset_filters=set(),
        category_filter_options=[],
        category_style_map={},
        selected_category_filters=set(),
        selected_excluded_category_filters=set(),
        selected_asset_filter_mode="or",
        selected_category_filter_mode="or",
        selected_rated_only=False,
        selected_sort="imported",
        search_query="",
        active_filter_pills=[],
        category_filter_count=0,
        filters_clear_href="/videos?asset_filters=1",
        library_views=[],
        current_videos_path="/videos",
        channel_entries_error=None,
        message=None,
        channel_page=1,
        next_import_page=1,
    )

    card = rendered[rendered.index('<article class="video-row"') :]
    assert (
        '<a class="video-title" href="/videos/42?next=/videos" title="Titre local">Titre local</a>'
        in card
    )
    assert '<a class="video-meta-link" href="/videos?channel_id=7">Chaîne locale</a>' in card
    assert "Téléchargement manuel" not in card
    assert card.index('<a class="video-title" href="/videos/42?next=/videos"') < card.index(
        'action="/videos/42/rating"'
    )
    assert card.index('<p class="video-meta">') < card.index('action="/videos/42/rating"')
    assert "video-row-rating" in card
    assert 'class="rating-control rating-control-minimal video-row-rating rating-tier-0"' in card
    assert "rating-star-empty" in card
    assert '<span aria-hidden="true">☆</span>' not in card
    assert '<span aria-hidden="true">★</span>' in card
    assert "Voir les détails" not in card
    assert "youtube.com" not in card.lower()
    assert ">YouTube<" not in card
    assert 'href="/videos/42/transcript"' not in card
    assert 'class="asset-label asset-label-video">Vidéo</span>' not in card
    assert 'class="asset-label asset-label-metadata">Métadonnées</span>' not in card
    assert 'class="asset-label asset-label-transcript">Transcript</span>' not in card
    assert 'class="asset-label asset-label-rating">★ Notées</span>' in rendered
    assert 'class="video-title-preview"' not in card
    assert "data-video-format-actions" not in card
    assert "format-toggle" not in card
    assert 'class="video-thumbnail-popover"' not in card
    assert 'src="/videos/42/thumbnail"' not in card
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

    response = media_routes.video_thumbnail(video.id, db)

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
        media_routes.video_thumbnail(video.id, db)

    assert exc_info.value.status_code == 404


def test_video_detail_page_renders_internal_page_without_youtube_action(monkeypatch):
    db = make_session()
    video = add_video(db)
    video.thumbnail_path = "/media/video/thumbnail.webp"
    video.comment = "À revoir pour le passage sur les exemples."
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert "Une vidéo à lire localement" in rendered
    assert 'href="/videos"' in rendered
    assert "Voir la source sur YouTube" not in rendered
    assert ">YouTube<" not in rendered
    assert 'class="video-detail-thumbnail"' not in rendered
    assert 'class="video-player-panel"' in rendered
    assert f'poster="/videos/{video.id}/thumbnail"' in rendered
    assert f'data-resume-key="raton:media-position:{video.id}:video"' in rendered
    assert f'<source src="/videos/{video.id}/video">' in rendered
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

    response = videos_routes.update_video_comment_form(
        video.id, comment="  Note perso\nsur deux lignes  ", return_to="/videos/1#notes", db=db
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/videos/1#notes"
    assert video.comment == "Note perso\nsur deux lignes"


def test_video_comment_form_clears_blank_comment():
    db = make_session()
    video = add_video(db)
    video.comment = "Ancienne note"
    db.commit()

    videos_routes.update_video_comment_form(
        video.id, comment="   ", return_to="/videos/1#notes", db=db
    )

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert 'id="transcript"' in rendered
    assert 'id="transcript-content"' in rendered
    assert "Bonjour depuis le transcript." in rendered
    assert 'id="discussion"' in rendered
    assert "Pose une question sur le transcript." not in rendered
    assert f'"askUrl": "/videos/{video.id}/transcript/chat"' in rendered
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

    labels_without_notes = shared.video_asset_labels(video)
    assert not any(label["kind"] == "notes" for label in labels_without_notes)

    (folder / "transcript.notes.txt").write_text("- Fait 1", encoding="utf-8")

    labels_with_notes = shared.video_asset_labels(video)
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

    card = rendered[rendered.index('<article class="video-row') :]
    card = card[: card.index("</article>")]
    assert 'class="asset-label' not in card
    assert 'class="category-label' not in card


def test_failed_llm_job_keeps_the_cost_of_a_truncated_response(monkeypatch):
    db = make_session()
    job = background_jobs.enqueue_llm_job(
        db, kind="chat", provider="anthropic", video_id=None, prompt="p"
    )

    class FakeProvider:
        def complete(self, prompt, on_text=None):
            tally = UsageTally("claude-haiku-5-5")
            tally.add(SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000))
            raise CompletionFailed("La réponse a été tronquée", tally)

    monkeypatch.setattr(background_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)

    background_jobs.run_llm_job(job.id)

    failed = db.get(LlmJob, job.id)
    assert failed.status == "failed"
    assert failed.model == "claude-haiku-5-5"
    assert failed.output_tokens == 1_000_000
    assert failed.cost_usd == pytest.approx(
        0.50 + 2.50
    )  # prompt over 100K tokens -> long-prompt tier


def fetch_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_fetch_video_sponsorblock_segments_inserts_rows(monkeypatch, tmp_path):
    db = make_session()
    video = add_video(db)
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,intro"))
    db.commit()

    monkeypatch.setattr(
        videos_routes,
        "fetch_sponsorblock_segments",
        lambda yt_video_id, categories: [
            {"category": "sponsor", "start_seconds": 10.0, "end_seconds": 20.0}
        ],
    )

    response = videos_routes.fetch_video_sponsorblock_segments(
        fetch_request(f"/videos/{video.id}/sponsors/fetch"), video.id, db
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "ok"
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

    monkeypatch.setattr(videos_routes, "fetch_sponsorblock_segments", fail)

    response = videos_routes.fetch_video_sponsorblock_segments(
        fetch_request(f"/videos/{video.id}/sponsors/fetch"), video.id, db
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert "impossible" in payload["message"].lower()
    assert (
        db.scalar(select(VideoSponsorSegment).where(VideoSponsorSegment.video_id == video.id))
        is None
    )


def test_sponsors_detect_route_is_gone():
    assert not hasattr(videos_routes, "detect_video_sponsor_segments")
    assert not any(
        getattr(route, "path", "") == "/videos/{video_id}/sponsors/detect"
        for route in main.app.routes
    )


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

    payload = api_routes.get_video_sponsor_segments(video.id, db)

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

    payload = api_routes.get_video_sponsor_segments(video.id, db)

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

    payload = api_routes.get_video_sponsor_segments(video.id, db)

    # La route renvoie toujours les segments : c'est le client qui décide de les
    # armer ou non à partir de `skip_enabled` (app/static/js/app.js).
    assert payload["skip_enabled"] is False
    assert payload["segments"] == [{"start": 30.0, "end": 60.0}]


def test_api_sponsor_segments_raises_404_for_unknown_video():
    db = make_session()

    with pytest.raises(HTTPException) as excinfo:
        api_routes.get_video_sponsor_segments(999, db)

    assert excinfo.value.status_code == 404


GENERATION_RESULT_TEXT = (
    "# Notes\n## Faits\n- Fait 1\n- Fait 2\n\n## Dates\nAucun élément identifié.\n\n"
    "## Lieux\nAucun élément identifié.\n\n## Acteurs\nAucun élément identifié.\n\n"
    "## Concepts\nAucun élément identifié.\n\n## Relations causales\nAucun élément identifié.\n\n"
    "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
    "## Résumé complet\nRésumé du contenu.\n\n- Point clé 1\n\n"
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

    assert json.loads(
        transcript_routes.transcript_job_status(video_id, job_id, BackgroundTasks(), db).body
    ) == {"status": "pending"}

    streamed = "# Résumé\n## Résumé court\nLigne 1.\n\n## Résumé complet\nDébut du résumé"
    polled = []

    class FakeProvider:
        def complete(self, prompt, on_text=None):
            on_text(streamed)
            polled.append(
                json.loads(
                    transcript_routes.transcript_job_status(
                        video_id, job_id, BackgroundTasks(), db
                    ).body
                )
            )
            return CompletionResult(
                text=GENERATION_RESULT_TEXT,
                model="claude-haiku-4-5",
                input_tokens=200,
                output_tokens=80,
            )

    monkeypatch.setattr(background_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(background_jobs, "PARTIAL_RESULT_INTERVAL_SECONDS", 0)

    background_jobs.run_llm_job(job_id)

    assert polled == [
        {
            "status": "pending",
            "partial_short_summary": "Ligne 1.",
            "partial_summary": "Début du résumé",
        }
    ]
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

    response = transcript_routes.transcript_job_status(video.id, job.id, background_tasks, db)
    assert json.loads(response.body)["status"] == "generated"
    assert len(scheduled) == 1
    fn, args, kwargs = scheduled[0]
    assert fn is transcript_routes.index_video_notes
    assert args[0] == video.id
    assert "- Fait 1\n- Fait 2" in args[1]
    assert kwargs == {}

    # Idempotent replay ("applied") must not reschedule indexing a second time.
    scheduled.clear()
    transcript_routes.transcript_job_status(video.id, job.id, background_tasks, db)
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert "Générer notes, résumé" in rendered
    assert f'action="/videos/{video.id}/transcript/generate"' in rendered
    assert 'data-tab="summary" role="tab" aria-selected="false" hidden' in rendered
    assert '<p id="video-short-summary" class="video-short-summary" hidden></p>' in rendered


def test_video_detail_page_shows_summary_tab_and_blurb_when_present(tmp_path):
    db = make_session()
    folder = tmp_path / "video"
    folder.mkdir()
    transcript = folder / "transcript.txt"
    summary = folder / "transcript.summary.txt"
    summary_short = folder / "transcript.summary_short.txt"
    transcript.write_text("Original brut.", encoding="utf-8")
    summary.write_text("Full summary content is present.", encoding="utf-8")
    summary_short.write_text("Résumé court existant.", encoding="utf-8")
    video = add_video(db)
    video.folder_path = str(folder)
    video.transcript_path = str(transcript)
    video.transcript_status = TranscriptStatus.downloaded
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert "Full summary content is present." in rendered
    assert (
        '<p id="video-short-summary" class="video-short-summary" >Résumé court existant.</p>'
        in rendered
    )
    assert 'data-tab="summary" role="tab" aria-selected="false" >Résumé</button>' in rendered


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    tab_order = re.findall(r'class="transcript-tab[^"]*" data-tab="([a-z-]+)"', rendered)
    assert tab_order[:3] == ["info", "segments", "raw"]
    assert tab_order[3:] == ["notes", "summary", "vtt", "personal-notes"]


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert '"enabled": false' in rendered


def test_video_detail_page_shows_segments_tab_without_any_segment():
    db = make_session()
    video = add_video(db)
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

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

    response = transcript_routes.transcript_job_status(video.id, job.id, BackgroundTasks(), db)

    assert json.loads(response.body) == {"status": "pending"}


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

    response = transcript_routes.transcript_job_status(video.id, job.id, BackgroundTasks(), db)

    assert response.status_code == 400
    assert "API indisponible." in json.loads(response.body)["message"]


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

    response = transcript_routes.chat_about_video_transcript(
        fetch_request(f"/videos/{video.id}/transcript/chat"),
        video.id,
        BackgroundTasks(),
        "Question ?",
        db,
    )
    payload = json.loads(response.body)
    assert payload["status"] == "queued"

    job = db.get(LlmJob, payload["job_id"])
    assert job.kind == "chat"
    assert job.provider == "anthropic"
    assert job.question == "Question ?"
    assert "Question ?" in job.prompt

    job.status = "done"
    job.result = "Réponse du LLM."
    db.commit()

    resolved_response = transcript_routes.transcript_job_status(
        video.id, job.id, BackgroundTasks(), db
    )
    resolved_payload = json.loads(resolved_response.body)

    assert resolved_payload["status"] == "ok"
    assert resolved_payload["messages"] == [
        {"role": "user", "content": "Question ?"},
        {"role": "assistant", "content": "Réponse du LLM."},
    ]
    assert (folder / "transcript.chat.json").exists()

    # Re-polling must not duplicate the appended messages.
    second_resolved = transcript_routes.transcript_job_status(
        video.id, job.id, BackgroundTasks(), db
    )
    assert len(json.loads(second_resolved.body)["messages"]) == 2


def test_transcript_chat_fetch_queues_job_and_resolves_after_background_task(monkeypatch, tmp_path):
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
        def complete(self, prompt, on_text=None):
            assert "Question ?" in prompt
            return CompletionResult(
                text="Réponse à Question ?",
                model="claude-haiku-4-5",
                input_tokens=30,
                output_tokens=10,
            )

    monkeypatch.setattr(background_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)

    scheduled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/transcript/chat",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = transcript_routes.chat_about_video_transcript(
        request, video.id, background_tasks, "Question ?", db
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "queued"
    job_id = payload["job_id"]
    assert scheduled == [(background_jobs.run_llm_job, (job_id,), {})]

    # Simulate the background task the request scheduled.
    background_jobs.run_llm_job(job_id)

    resolved = transcript_routes.transcript_job_status(video.id, job_id, BackgroundTasks(), db)
    resolved_payload = json.loads(resolved.body)

    assert resolved_payload["status"] == "ok"
    assert resolved_payload["messages"] == [
        {"role": "user", "content": "Question ?"},
        {"role": "assistant", "content": "Réponse à Question ?"},
    ]
    assert (folder / "transcript.chat.json").exists()
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "prompt"))
    assert job is not None
    assert job.video_id == video.id
    assert job.channel_id == video.channel_id
    assert "Prompt envoyé sur Une vidéo à lire localement: Question ?" in job.message


def test_transcript_chat_clear_fetch_returns_empty_messages(tmp_path):
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
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/transcript/chat/clear",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = transcript_routes.clear_video_transcript_chat(request, video.id, db)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["messages"] == []
    assert not (folder / "transcript.chat.json").exists()


def test_video_transcript_page_redirects_to_video_detail_anchor():
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}/transcript",
            "query_string": b"message=ok",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = transcript_routes.video_transcript_page(request, video.id, db)

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert 'class="audio-player-panel audio-player-panel-trigger"' in rendered
    assert 'class="video-player-panel media-thumbnail-panel"' in rendered
    assert 'class="audio-player-thumbnail"' in rendered
    assert f'src="/videos/{video.id}/thumbnail"' in rendered
    assert "data-play-track" in rendered
    assert f'data-track-id="{video.id}"' in rendered
    assert f'data-track-src="/videos/{video.id}/audio"' in rendered
    assert f'data-track-thumb="/videos/{video.id}/thumbnail"' in rendered
    assert f'data-track-resume-key="raton:media-position:{video.id}:audio"' in rendered
    assert f'data-track-activity-url="/videos/{video.id}/activity"' in rendered
    assert f'data-track-detail-url="/videos/{video.id}"' in rendered
    assert '<audio controls preload="metadata" src="/videos/' not in rendered
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert 'class="audio-player-panel"' in rendered
    assert 'class="audio-player-panel audio-player-panel-trigger"' not in rendered
    assert '<audio controls preload="metadata" src="/videos/' in rendered
    assert f'src="/videos/{video.id}/audio"' in rendered
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
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/video/delete",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.delete_video_media_form(
        request, video.id, "video", return_to=f"/videos/{video.id}", db=db
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos/{video.id}?")
    assert not video_file.exists()
    assert audio_file.exists()
    assert video.video_path is None
    assert video.audio_path == str(audio_file)
    assert video.media_type == "audio"
    assert video.file_size_bytes == len(b"audio bytes")


def test_delete_video_media_fetch_returns_json(tmp_path):
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
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/video/delete",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.delete_video_media_form(
        request, video.id, "video", return_to=f"/videos/{video.id}", db=db
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "deleted"
    assert not video_file.exists()
    assert video.video_path is None


def test_delete_video_media_fetch_returns_json_error_when_already_missing(tmp_path):
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
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/video/delete",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.delete_video_media_form(
        request, video.id, "video", return_to=f"/videos/{video.id}", db=db
    )

    assert response.status_code == 400
    payload = json.loads(response.body)
    assert payload["status"] == "failed"


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
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/audio/delete",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.delete_video_media_form(
        request, video.id, "audio", return_to=f"/videos/{video.id}", db=db
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/videos/{video.id}?")
    assert video_file.exists()
    assert not audio_file.exists()
    assert video.video_path == str(video_file)
    assert video.audio_path is None
    assert video.media_type == "video"
    assert video.file_size_bytes == len(b"video bytes")


def test_download_video_media_queues_job_and_returns_json(monkeypatch):
    db = make_session()
    video = add_video(db)
    monkeypatch.setattr(videos_routes, "run_manual_download_job", lambda *args, **kwargs: None)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/audio/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    response = videos_routes.download_video_media_form(
        request, BackgroundTasks(), video.id, "audio", db=db
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/videos/download-jobs/{payload['job_id']}"
    job = db.get(DownloadJob, payload["job_id"])
    assert job is not None
    assert job.video_id == video.id


def test_download_video_media_returns_internal_next_as_return_to(monkeypatch):
    db = make_session()
    video = add_video(db)
    monkeypatch.setattr(videos_routes, "run_manual_download_job", lambda *args, **kwargs: None)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/video/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    response = videos_routes.download_video_media_form(
        request,
        BackgroundTasks(),
        video.id,
        "video",
        "1080",
        "/videos?channel_id=1&section=shorts",
        db=db,
    )
    assert json.loads(response.body)["return_to"] == "/videos?channel_id=1&section=shorts"

    response = videos_routes.download_video_media_form(
        request, BackgroundTasks(), video.id, "video", "1080", "https://evil.example/", db=db
    )
    assert "return_to" not in json.loads(response.body)


def test_download_video_media_rejects_invalid_format():
    db = make_session()
    video = add_video(db)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/media/subtitles/download",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    with pytest.raises(HTTPException):
        videos_routes.download_video_media_form(
            request, BackgroundTasks(), video.id, "subtitles", db=db
        )


def test_retry_video_transcript_queues_job_and_returns_json(monkeypatch):
    db = make_session()
    video = add_video(db)
    monkeypatch.setattr(videos_routes, "run_transcript_retry_job", lambda *args, **kwargs: None)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/transcript/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    response = videos_routes.retry_video_transcript_form(
        request, BackgroundTasks(), video.id, db=db
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/videos/download-jobs/{payload['job_id']}"
    job = db.get(DownloadJob, payload["job_id"])
    assert job is not None
    assert job.video_id == video.id


def test_retry_video_transcript_rejects_missing_video():
    db = make_session()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/999/transcript/download",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    with pytest.raises(HTTPException):
        videos_routes.retry_video_transcript_form(request, BackgroundTasks(), 999, db=db)


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

    monkeypatch.setattr(
        background_jobs, "retry_transcript_download", fake_retry_transcript_download
    )
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)

    background_jobs.run_transcript_retry_job(job.id, video.id)

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

    monkeypatch.setattr(
        background_jobs, "retry_transcript_download", fake_retry_transcript_download
    )
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)

    background_jobs.run_transcript_retry_job(job.id, video.id)

    completed_job = db.get(DownloadJob, job.id)
    assert completed_job.status == "failed"
    assert "Aucun sous-titre disponible" in completed_job.message


def test_video_detail_back_link_returns_to_channel_page(monkeypatch):
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "query_string": f"next=/videos%3Fchannel_id%3D{video.channel_id}%26page%3D2".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert f'href="/videos?channel_id={video.channel_id}&amp;page=2"' in rendered
    assert "← Retour à la chaîne" in rendered


def test_video_detail_back_link_returns_to_playlist_page(monkeypatch):
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "query_string": b"next=/playlists/7",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

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
            "path": f"/videos/{video.id}/audio",
            "headers": [(b"range", b"bytes=2-5")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.video_audio(video.id, request, db)

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
            "path": f"/videos/{video.id}/video",
            "headers": [(b"range", b"bytes=1-4")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.video_file(video.id, request, db)

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
            "path": f"/videos/{video.id}/video",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = media_routes.video_file_head(video.id, request, db)

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.video_detail_page(request, video.id, db)
    rendered = response.body.decode()

    assert "Métadonnées" in rendered
    assert 'class="video-player-panel media-thumbnail-panel"' in rendered
    assert f'src="/videos/{video.id}/thumbnail"' in rendered
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()
    response = media_routes.video_subtitles(video.id, db)

    # Pas d'attribut `default` : il forcerait l'affichage à chaque chargement,
    # même quand les sous-titres sont désactivés dans le lecteur (iPhone).
    assert (
        f'<track kind="subtitles" src="/videos/{video.id}/subtitles" label="Sous-titres">'
        in rendered
    )
    assert str(response.path) == str(subtitle)
    assert response.media_type == "text/vtt; charset=utf-8"


def test_download_form_does_not_force_a_subtitle_language(monkeypatch):
    # A forced language asks YouTube for an auto-translation (HTTP 429): the form leaves the track choice to the server.
    db = make_session()
    scheduled = []
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = videos_routes.download_video_form(
        request,
        background_tasks,
        url="https://youtube.com/watch?v=en123",
        media_type=["metadata"],
        download_transcript=True,
        return_to="/videos/import",
        db=db,
    )

    assert '"return_to":"/videos/import"' in response.body.decode()
    assert scheduled[0][1][5] is None


def test_import_page_has_form_without_subtitle_language_and_menu_entry():
    db = make_session()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos/import",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.import_video_page(request, db).body.decode()

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
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from app.db.session import get_db

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    main.app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(main.app).get("/videos/import")
    finally:
        main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert 'action="/videos/download"' in response.text


def test_download_form_queues_ajax_job(monkeypatch):
    db = make_session()
    scheduled = []
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = videos_routes.download_video_form(
        request,
        background_tasks,
        url="https://youtube.com/watch?v=abc123",
        media_type=["audio"],
        download_transcript=True,
        return_to="/videos",
        db=db,
    )

    payload = response.body.decode()
    job = db.scalar(select(DownloadJob))
    assert response.status_code == 200
    assert job.status == "queued"
    assert f'"job_id":{job.id}' in payload
    assert f"/videos/download-jobs/{job.id}" in payload
    assert scheduled == [
        (
            background_jobs.run_manual_download_job,
            (
                job.id,
                "https://youtube.com/watch?v=abc123",
                ["audio", "metadata"],
                True,
                None,
                None,
                "both",
            ),
            {},
        )
    ]

    status = videos_routes.download_job_status(job.id, db)
    assert status["status"] == "queued"
    assert status["done"] is False


def test_download_form_accepts_metadata_only_ajax_job(monkeypatch):
    db = make_session()
    scheduled = []
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = videos_routes.download_video_form(
        request,
        background_tasks,
        url="https://youtube.com/watch?v=meta123",
        media_type=["metadata"],
        download_transcript=True,
        return_to="/videos",
        db=db,
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 200
    assert job.status == "queued"
    assert scheduled == [
        (
            background_jobs.run_manual_download_job,
            (job.id, "https://youtube.com/watch?v=meta123", ["metadata"], True, None, None, "both"),
            {},
        )
    ]


def test_download_form_queues_category_labels(monkeypatch):
    db = make_session()
    scheduled = []
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/download",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = videos_routes.download_video_form(
        request,
        background_tasks,
        url="https://youtube.com/watch?v=cat123",
        media_type=["metadata"],
        download_transcript=False,
        preset_categories=["maker", "science"],
        custom_categories="Interview, maker",
        return_to="/videos",
        db=db,
    )

    job = db.scalar(select(DownloadJob))
    assert response.status_code == 200
    assert scheduled == [
        (
            background_jobs.run_manual_download_job,
            (
                job.id,
                "https://youtube.com/watch?v=cat123",
                ["metadata"],
                False,
                "maker,science,interview",
                None,
                "both",
            ),
            {},
        )
    ]
    assert "interview" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_video_detail_page_returns_404_for_unknown_video():
    db = make_session()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos/999",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        videos_routes.video_detail_page(request, 999, db)

    assert exc_info.value.status_code == 404


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": f"channel_id={video.channel_id}".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, video.channel_id, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"q=architecture",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"q=ete+Jardinage",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

    assert "Episode 12" not in rendered
    assert "Jardinage d&#39;été" in rendered
    assert 'name="q" type="search" value="ete Jardinage"' in rendered

    rendered = videos_routes.videos_page(
        Request({**request.scope, "query_string": b"q=jardinage"}), None, 1, db
    ).body.decode()
    frame = rendered[
        rendered.index('<turbo-frame id="library-results"') : rendered.index("</turbo-frame>")
    ]

    # The note match is the most recent import, yet the title match comes first.
    assert frame.index("Jardinage d&#39;été") < frame.index("Episode 12")


def test_videos_page_search_without_result_names_the_query(monkeypatch):
    db = make_session()
    add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"q=introuvable",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

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

    default_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    default_response = videos_routes.videos_page(default_request, None, 1, db)
    default_rendered = default_response.body.decode()

    assert "Une vidéo à lire localement" in default_rendered
    assert "Audio local" in default_rendered
    assert "Métadonnées seules" not in default_rendered

    metadata_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset=metadata",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    metadata_response = videos_routes.videos_page(metadata_request, None, 1, db)
    metadata_rendered = metadata_response.body.decode()

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

    default_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    default_rendered = videos_routes.videos_page(default_request, None, 1, db).body.decode()
    default_list = default_rendered[default_rendered.index('<div class="video-row-list">') :]

    assert default_list.index("Import récent") < default_list.index("Publication récente")
    assert '<option value="imported" selected>Import récent</option>' in default_rendered

    published_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"sort=published",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    published_rendered = videos_routes.videos_page(published_request, None, 1, db).body.decode()
    published_list = published_rendered[published_rendered.index('<div class="video-row-list">') :]

    assert published_list.index("Publication récente") < published_list.index("Import récent")
    assert '<option value="published" selected>Publication récente</option>' in published_rendered

    channel_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": f"channel_id={older_publication_recent_import.channel_id}".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    channel_rendered = videos_routes.videos_page(
        channel_request, str(older_publication_recent_import.channel_id), 1, db
    ).body.decode()
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset=imported",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset=imported",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&filter_mode=and&asset=video&rated=1",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset_filter_mode=or&category_filter_mode=or&rated=1",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

    assert rated.title in rendered
    assert '<nav class="library-subnav" aria-label="Sous-bibliothèques">' in rendered
    assert (
        '<a class="lg active" href="/videos?asset_filters=1&amp;asset_filter_mode=or&amp;category_filter_mode=or&amp;rated=1">Notés</a>'
        in rendered
    )


def test_videos_page_empty_sub_library_filters_show_all_videos(monkeypatch):
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset_filter_mode=or&category_filter_mode=or",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&filter_mode=or&asset=video&rated=1",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&exclude_asset=metadata",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&filter_mode=and&category=maker&category=science",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&asset=video&exclude_category=maker",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&category=cuisine&exclude_asset=shorts",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": (
                b"asset_filters=1&asset_filter_mode=or&category_filter_mode=and"
                b"&asset=video&category=maker&category=science"
            ),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

    assert "Vidéo maker science" in rendered
    assert "Vidéo maker seule" not in rendered
    assert "Fiche maker science" not in rendered
    assert 'name="asset_filter_mode" type="radio" value="or" checked' in rendered
    assert 'name="category_filter_mode" type="radio" value="and" checked' in rendered


def test_video_categories_form_saves_presets_and_custom_labels():
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/videos/{video.id}/categories",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.update_video_categories_form(
        request,
        video.id,
        preset_categories=["maker", "science"],
        custom_categories="Interview, maker",
        return_to=f"/videos/{video.id}",
        db=db,
    )

    assert response.headers["location"] == f"/videos/{video.id}"
    assert video.category_labels == "maker,science,interview"
    assert "interview" in [
        item["label"] for item in json.loads(db.get(AppSetting, "video_category_labels").value)
    ]


def test_videos_page_accepts_empty_channel_filter(monkeypatch):
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"asset_filters=1&channel_id=&asset=video",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, "", 1, db)
    rendered = response.body.decode()

    assert response.status_code == 200
    assert "Bibliothèque" in rendered
    assert video.title in rendered


def test_channel_metadata_import_form_queues_ajax_job(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    db.add(channel)
    db.commit()
    scheduled = []
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/channels/{channel.id}/import-metadata",
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = channels_routes.import_channel_metadata_form(
        request,
        background_tasks,
        channel.id,
        page=2,
        return_to=f"/videos?channel_id={channel.id}",
        db=db,
    )

    payload = response.body.decode()
    job = db.scalar(select(DownloadJob))
    assert response.status_code == 200
    assert job.status == "queued"
    assert job.channel_id == channel.id
    assert f'"job_id":{job.id}' in payload
    assert f"/jobs/{job.id}" in payload
    assert scheduled == [
        (background_jobs.run_channel_metadata_import_job, (job.id, channel.id, 2, "videos"), {})
    ]

    status = videos_routes.job_status(job.id, db)
    assert status["status"] == "queued"
    assert status["done"] is False


def test_channel_metadata_import_job_imports_one_page(monkeypatch):
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Chaîne test")
    job = DownloadJob(channel=channel, status="queued", message="queued")
    db.add(job)
    db.commit()
    calls = []
    monkeypatch.setattr(background_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        background_jobs,
        "scan_channel_section",
        lambda db, channel, **kwargs: calls.append(kwargs) or 25,
    )

    background_jobs.run_channel_metadata_import_job(job.id, channel.id, page=1)

    assert len(calls) == 1
    assert callable(calls[0].pop("should_stop"))
    assert calls == [
        {
            "page": 1,
            "page_size": background_jobs.CHANNEL_VIDEO_PAGE_SIZE,
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": f"channel_id={channel.id}".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, channel.id, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": f"channel_id={channel.id}&section=shorts".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, channel.id, 1, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": f"channel_id={channel.id}{query}".encode(),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, channel.id, 1, db).body.decode()

    assert ("Short vertical" in rendered) == (expected == "shorts")
    assert ("Vidéo longue" in rendered) == (expected == "videos")


def test_content_views_only_link_to_raton_pages():
    db = make_session()
    video = add_video(db)
    channel = video.channel

    dashboard = shared.templates.env.get_template("dashboard_history.html").render(
        channel_count=1,
        rated_channel_count=1,
        video_count=1,
        regular_video_count=1,
        short_count=0,
        downloaded_media_count=1,
        transcript_count=0,
        history_days=playback.history_day_groups(
            [
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
                    video=video,
                    channel=channel,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                )
            ]
        ),
        playback_time_stats=playback.empty_playback_stats(),
        category_style_map={},
        chat_widget_config={
            "defaultScope": "library",
            "llmProviderLabel": "Anthropic",
            "scopes": {
                "library": {
                    "askUrl": "/chat",
                    "clearUrl": "/chat/clear",
                    "jobUrlTemplate": "/chat/jobs/{job_id}",
                    "messages": [],
                    "coverageNote": None,
                }
            },
        },
    )
    channels = shared.templates.env.get_template("channels.html").render(channels=[channel])
    detail = shared.templates.env.get_template("video_detail.html").render(
        video=video,
        back_path="/videos",
        back_label="Retour à la bibliothèque",
        message=None,
        message_level="success",
        display_transcript=None,
        chat_messages=[],
    )

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
        videos_routes.log_video_activity(
            video.id,
            media_type=media_type,
            position_seconds=position,
            duration_seconds=600,
            watched_seconds=10,
            db=db,
        )
        job = db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played")
            .order_by(DownloadJob.id.desc())
        ).first()
        job.created_at = base + timedelta(minutes=offset)
        db.commit()

    positions = playback.latest_playback_positions(db, video.id)

    assert positions["video"] == {
        "position_seconds": 252.5,
        "at_ms": int((base + timedelta(minutes=2)).timestamp() * 1000),
    }
    assert positions["audio"] == {
        "position_seconds": 45,
        "at_ms": int((base + timedelta(minutes=1)).timestamp() * 1000),
    }

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert 'data-resume-server-position="252.5"' in rendered
    assert f'data-resume-server-at="{positions["video"]["at_ms"]}"' in rendered


def test_video_detail_omits_server_resume_position_without_playback():
    db = make_session()
    video = add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert playback.latest_playback_positions(db, video.id) == {}
    assert "data-resume-server-position" not in rendered


def test_video_activity_logs_media_playback():
    db = make_session()
    video = add_video(db)

    response = videos_routes.log_video_activity(
        video.id,
        media_type="video",
        position_seconds=252,
        duration_seconds=600,
        watched_seconds=83,
        db=db,
    )
    job = db.scalar(select(DownloadJob).where(DownloadJob.status == "played"))

    assert response == {"status": "logged"}
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

    videos_routes.log_video_activity(
        video.id,
        media_type="video",
        position_seconds=300,
        duration_seconds=600,
        watched_seconds=10,
        db=db,
    )
    assert db.get(Video, video.id).watched_at is None

    videos_routes.log_video_activity(
        video.id,
        media_type="video",
        position_seconds=540,
        duration_seconds=600,
        watched_seconds=10,
        db=db,
    )
    assert db.get(Video, video.id).watched_at is not None


def test_library_pages_share_the_nouveautes_historique_exploration_subnav():
    db = make_session()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    page_one = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db)
    rendered_one = page_one.body.decode()
    page_two = dashboard_routes.dashboard_new_videos_page(request, page=2, db=db)
    rendered_two = page_two.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/nouveautes",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_new_videos_page(request, page=1, db=db).body.decode()

    for shown in ("V-video", "S-short", "B-video", "B-short"):
        assert shown in rendered
    for hidden in ("V-short", "S-video", "N-video", "N-short", "Sans cloche"):
        assert hidden not in rendered


def test_history_row_drops_the_dates_and_moves_the_file_size_next_to_the_stars():
    db = make_session()
    history_playback_jobs(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()
    history = rendered
    footer = history.split('<div class="video-card-footer">')[1]

    assert "Publié le" not in history
    assert "Vu le" not in history
    assert '<span class="video-card-footer-size">5.0 Mo</span>' in footer
    assert footer.index("video-card-footer-size") < footer.index("rating-control")


def test_old_reprises_url_redirects_to_historique_keeping_the_page():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/reprises",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"page=3",
        }
    )

    response = dashboard_routes.dashboard_resume_page_redirect(request)

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/historique",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    page_one = dashboard_routes.dashboard_history_page(request, page=1, db=db)
    rendered_one = page_one.body.decode()
    page_two = dashboard_routes.dashboard_history_page(request, page=2, db=db)
    rendered_two = page_two.body.decode()

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

    groups = playback.history_day_groups(jobs, now)

    assert [group["label"] for group in groups] == ["Aujourd’hui", "Hier", "Mar. 17 juin 2025"]
    assert [len(group["jobs"]) for group in groups] == [2, 1, 1]
    assert groups[0]["full_label"] == "Ven. 20 juin 2025"
    assert groups[1]["full_label"] == "Jeu. 19 juin 2025"
    assert groups[2]["label"] == groups[2]["full_label"]
    assert groups[0]["jobs"] == jobs[:2]
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
    seconds_by_day = playback.playback_seconds_by_day(jobs, now)

    groups = playback.history_day_groups(jobs[:1], now, seconds_by_day)

    assert groups[0]["seconds"] == 900.0
    assert len(groups[0]["jobs"]) == 1


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/historique",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/historique",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard(request, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()

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

    stats = playback.playback_time_stats(jobs, now)

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    dashboard_rendered = settings_routes.settings_page(request, db).body.decode()
    history_rendered = dashboard_routes.dashboard_history_page(request, page=1, db=db).body.decode()
    logs_rendered = settings_routes.logs_page(request, db).body.decode()

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

    all_logs = playback.dashboard_media_activity_logs(db)
    limited_logs = playback.dashboard_media_activity_logs(db, limit=0)

    assert len(all_logs) == 1
    assert "0:11" in all_logs[0].message
    assert limited_logs == []


def test_channels_page_shows_rated_channels_by_default():
    db = make_session()
    rated = Channel(url="https://example.test/rated", name="Rated", rating=5)
    unrated = Channel(url="https://example.test/unrated", name="Unrated", rating=0)
    db.add_all([rated, unrated])
    db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    response = channels_routes.channels_page(request, db=db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = channels_routes.channels_page(request, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"sort=activity",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = channels_routes.channels_page(request, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = channels_routes.channels_page(request, db=db).body.decode()

    assert rendered.index("Newer") < rendered.index("Older")
    assert rendered.index("Older") < rendered.index("Inactive")
    assert '<option value="activity" selected>Dernier média joué</option>' in rendered


def test_channels_page_sorts_alphabetically():
    db = make_session()
    beta = Channel(url="https://example.test/beta", name="Beta", rating=5)
    alpha = Channel(url="https://example.test/alpha", name="Alpha", rating=1)
    db.add_all([beta, alpha])
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"sort=alpha",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = channels_routes.channels_page(request, db=db).body.decode()

    assert rendered.index("Alpha") < rendered.index("Beta")
    assert '<option value="alpha" selected>A-Z</option>' in rendered


def test_channels_page_can_show_all_channels():
    db = make_session()
    rated = Channel(url="https://example.test/rated", name="Rated", rating=5)
    unrated = Channel(url="https://example.test/unrated", name="Unrated", rating=0)
    db.add_all([rated, unrated])
    db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"rated=false",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    response = channels_routes.channels_page(request, db=db)
    rendered = response.body.decode()

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

    rated_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"q=maker",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    rated_rendered = channels_routes.channels_page(rated_request, db=db).body.decode()

    assert "Rated" in rated_rendered
    assert "Cinema" not in rated_rendered
    assert 'name="q" type="search" value="maker"' in rated_rendered

    all_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"rated=false&q=cinema",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    all_rendered = channels_routes.channels_page(all_request, db=db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"rated=false&sort=alpha&q=CINEMA",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = channels_routes.channels_page(request, db=db).body.decode()
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

    response = channels_routes.update_channel_categories_form(
        channel.id,
        preset_categories=["maker"],
        custom_categories="Science, maker",
        return_to="/channels",
        db=db,
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = channels_routes.channels_page(request, db=db)
    rendered = response.body.decode()

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

    response = channels_routes.rate_channel_form(
        channel.id, rating=2, return_to="/channels?rated=true", db=db
    )

    assert channel.rating == 2
    assert response.headers["location"] == "/channels?rated=true"


def test_rating_answers_json_to_fetch_instead_of_redirecting():
    db = make_session()
    video = add_video(db)
    request = SimpleNamespace(headers={"x-requested-with": "fetch"})

    video_response = videos_routes.rate_video_form(video.id, 4, "/videos", db, request)
    channel_response = channels_routes.rate_channel_form(
        video.channel.id, 3, "/channels", db, request
    )

    assert video.rating == 4
    assert video_response.status_code == 200
    assert json.loads(video_response.body) == {"rating": 4}
    assert video.channel.rating == 3
    assert json.loads(channel_response.body) == {"rating": 3}


def test_base_layout_keeps_scroll_position_on_page_refresh():
    # Without this meta a form that redirects to its own page scrolls back to
    # the top; app.js relies on it (see the turbo:before-fetch-response hook).
    source = pathlib.Path("app/templates/base.html").read_text(encoding="utf-8")
    assert '<meta name="turbo-refresh-scroll" content="preserve">' in source


def test_rating_forms_opt_out_of_turbo_navigation():
    # The stars are repainted in place by app.js; a Turbo submission would
    # follow the redirect and reload the whole page on top of it.
    for template in ("_macros.html", "channels.html", "channel_videos.html", "video_detail.html"):
        source = (pathlib.Path("app/templates") / template).read_text(encoding="utf-8")
        forms = re.findall(r'<form class="rating-control[^>]*>', source)
        assert forms, template
        assert all('data-turbo="false"' in form for form in forms), template


def test_new_channels_are_rated_by_default(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channels_routes,
        "extract_channel_info",
        lambda url: {"name": "Nouvelle chaîne", "yt_channel_id": "UC123"},
    )

    response = channels_routes.add_channel("https://example.test/channel", db)
    channel = db.scalar(select(Channel).where(Channel.url == "https://example.test/channel"))

    assert response.headers["location"] == f"/channels?sort=added&added_channel_id={channel.id}"
    assert channel is not None
    assert channel.rating == 1


def channels_request(query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/channels",
            "query_string": query_string,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_channels_page_shows_added_channel_toast_with_link():
    db = make_session()
    channel = Channel(url="https://example.test/channel", name="Nouvelle chaîne", rating=1)
    db.add(channel)
    db.commit()

    request = channels_request(f"added_channel_id={channel.id}&sort=alpha".encode())
    rendered = channels_routes.channels_page(request, db=db).body.decode()

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

    for query_string in (b"", b"added_channel_id=9999", b"added_channel_id=abc"):
        rendered = channels_routes.channels_page(
            channels_request(query_string), db=db
        ).body.decode()
        assert "data-toast" not in rendered


def test_redirect_message_is_rendered_as_a_toast_not_an_inline_notice():
    db = make_session()
    db.add(Channel(url="https://example.test/channel", name="Léo Duff", rating=1))
    db.commit()

    message = "25 fiches vidéos importées pour Léo Duff."
    rendered = channels_routes.channels_page(
        channels_request(urlencode({"message": message}).encode()), db=db
    ).body.decode()

    assert f'<p class="toast-text">{message}</p>' in rendered
    assert 'class="toast" role="status" data-toast data-toast-param="message level"' in rendered
    assert 'class="notice' not in rendered


def test_redirect_error_message_is_rendered_as_an_error_toast():
    db = make_session()

    rendered = channels_routes.channels_page(
        channels_request(urlencode({"level": "error", "message": "Import impossible."}).encode()),
        db=db,
    ).body.decode()

    assert (
        'class="toast error" role="alert" data-toast data-toast-param="message level"' in rendered
    )
    assert '<p class="toast-text">Import impossible.</p>' in rendered


def test_redirect_messages_are_rendered_by_the_base_layout_only():
    # A page that renders `message` itself would show it twice, and away from
    # the toast stack.
    for template in pathlib.Path("app/templates").glob("*.html"):
        if template.name == "base.html":
            continue
        assert "{% if message %}" not in template.read_text(encoding="utf-8"), template.name


def test_add_channel_with_a_name_shows_youtube_candidates_instead_of_guessing(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channels_routes,
        "extract_channel_info",
        lambda value: pytest.fail("must not resolve a name"),
    )

    response = channels_routes.add_channel("Léo Duff", db, preset_categories=["tech"])

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
        channels_routes,
        "search_channels",
        lambda query: [
            youtube_candidate(),
            youtube_candidate("UCknown", "Leo Duff", "@LeFohShow", 341),
        ],
    )

    request = channels_request("youtube_q=Léo Duff&youtube_categories=tech&sort=alpha".encode())
    rendered = channels_routes.channels_page(request, db=db).body.decode()

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
        channels_routes,
        "search_channels",
        lambda query: (_ for _ in ()).throw(RuntimeError("réseau")),
    )

    rendered = channels_routes.channels_page(
        channels_request(b"youtube_q=test"), db=db
    ).body.decode()

    assert "Recherche YouTube impossible : réseau" in rendered


def test_add_channel_refuses_a_channel_already_in_the_library(monkeypatch):
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
        channels_routes,
        "extract_channel_info",
        lambda value: {
            "url": "https://www.youtube.com/@deja-la",
            "name": "Déjà là",
            "yt_channel_id": "UC123",
        },
    )

    response = channels_routes.add_channel("@deja-la", db)

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

    monkeypatch.setattr(yt_service, "YoutubeDL", FakeYoutubeDL)

    results = yt_service.search_channels("Léo Duff", limit=5)

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
    assert yt_service.search_channels("   ") == []


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


def test_add_channel_returns_not_found_for_missing_handle(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channels_routes,
        "extract_channel_info",
        lambda channel_input: (_ for _ in ()).throw(ChannelNotFoundError("missing")),
    )

    with pytest.raises(HTTPException) as exc:
        channels_routes.add_channel("@missing-handle", db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Chaîne introuvable"


def test_api_create_channel_saves_resolved_url_from_name(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        api_routes,
        "extract_channel_info",
        lambda channel_input: {
            "url": "https://www.youtube.com/@api-channel",
            "name": "Chaîne API",
            "yt_channel_id": "UCAPI",
        },
    )

    channel = api_routes.create_channel(api_routes.ChannelCreate(url="Chaîne API"), db)

    assert channel.name == "Chaîne API"
    assert channel.url == "https://www.youtube.com/@api-channel"


def test_api_create_channel_returns_not_found_for_missing_handle(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        api_routes,
        "extract_channel_info",
        lambda channel_input: (_ for _ in ()).throw(ChannelNotFoundError("missing")),
    )

    with pytest.raises(HTTPException) as exc:
        api_routes.create_channel(api_routes.ChannelCreate(url="@missing-handle"), db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Channel not found"


def test_add_channel_saves_category_labels(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channels_routes,
        "extract_channel_info",
        lambda url: {"name": "Nouvelle chaîne", "yt_channel_id": "UC123"},
    )

    response = channels_routes.add_channel(
        "https://example.test/channel",
        db,
        preset_categories=["maker"],
        custom_categories="Science, maker",
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

    detail_response = videos_routes.rate_video_form(video.id, 4, f"/videos/{video.id}", db)
    external_response = videos_routes.rate_video_form(
        video.id, 3, "https://youtube.com/watch?v=abc123", db
    )

    assert detail_response.headers["location"] == f"/videos/{video.id}"
    assert external_response.headers["location"] == "/videos"


def test_settings_form_updates_media_root_and_quota(tmp_path):
    db = make_session()

    response = settings_routes.settings_form(
        str(tmp_path), 2.5, "Maker\nScience\nmaker\nHistoire", db
    )

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "media_root").value == str(tmp_path)
    assert db.get(AppSetting, "global_quota_bytes").value == str(int(2.5 * 1024 * 1024 * 1024))
    assert json.loads(db.get(AppSetting, "video_category_labels").value) == [
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

    response = settings_routes.settings_form(str(tmp_path), 2.5, "", db, category_styles)

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

    response = settings_routes.settings_form(
        str(tmp_path), 2.5, "Maker\nScience", db, "", library_views
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

    assert "Catégories sans barre de progression" in rendered
    assert 'value="maker"' in rendered
    assert 'name="no_progress_categories" value="musique" checked' in rendered
    # "amv" is a default selection but isn't a registered category label here,
    # so it still surfaces as a (checked, uncolored) option instead of vanishing.
    assert 'name="no_progress_categories" value="amv" checked' in rendered


def test_ensure_default_settings_seeds_defaults_without_llm_provider():
    from app.services.settings import ensure_default_settings

    db = make_session()

    ensure_default_settings(db)

    assert db.get(AppSetting, "media_root") is not None
    assert db.get(AppSetting, "llm_provider") is None


def test_settings_form_saves_no_progress_categories(tmp_path):
    db = make_session()

    response = settings_routes.settings_form(str(tmp_path), 2.5, "", db, "", "", ["musique"])

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "no_progress_category_labels").value == "musique"


def test_settings_form_saves_sponsor_segment_categories(tmp_path):
    db = make_session()

    response = settings_routes.settings_form(
        str(tmp_path), 2.5, "", db, "", "", [], 120, 30, 120, 180, ["sponsor", "intro"]
    )

    assert response.headers["location"] == "/settings"
    assert db.get(AppSetting, "sponsor_segment_categories").value == "sponsor,intro"


def test_settings_page_renders_sponsor_segment_category_checkboxes(tmp_path):
    db = make_session()
    db.add(AppSetting(key="media_root", value=str(tmp_path)))
    db.add(AppSetting(key="global_quota_bytes", value=str(2 * 1024 * 1024 * 1024)))
    db.add(AppSetting(key="sponsor_segment_categories", value="sponsor,outro"))
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

    assert "Segments sponsorisés" in rendered
    assert 'name="sponsor_segment_categories" value="sponsor" checked' in rendered
    assert 'name="sponsor_segment_categories" value="outro" checked' in rendered
    assert 'name="sponsor_segment_categories" value="selfpromo">' in rendered  # present, unchecked


def test_get_sponsor_segment_categories_defaults_to_all():
    from app.services.settings import (
        SPONSOR_SEGMENT_CATEGORY_CHOICES,
        get_sponsor_segment_categories,
    )

    db = make_session()
    assert get_sponsor_segment_categories(db) == SPONSOR_SEGMENT_CATEGORY_CHOICES


def test_get_sponsor_segment_categories_filters_unknown_values():
    from app.services.settings import get_sponsor_segment_categories

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

    settings_routes.settings_form(
        media_root=str(tmp_path),
        quota_gb=10.0,
        db=db,
        sponsor_skip_enabled="on",
    )
    assert get_sponsor_skip_enabled(db) is True

    settings_routes.settings_form(
        media_root=str(tmp_path),
        quota_gb=10.0,
        db=db,
        sponsor_skip_enabled="",
    )
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

    assert "Coûts LLM" in rendered
    assert "Notes structurées" in rendered
    assert "$0.0020" in rendered


def test_settings_page_shows_never_scanned_when_no_auto_scan_recorded(tmp_path):
    db = make_session()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

    assert "Suivi automatique" in rendered
    assert "Aucun scan automatique n'a encore tourné." in rendered


def test_settings_page_shows_last_auto_scan_result(tmp_path):
    db = make_session()
    record_scan_result(db, {"status": "completed", "downloaded": 5, "deleted": 0})
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = settings_routes.settings_page(request, db)
    rendered = response.body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = videos_routes.videos_page(request, None, 1, db)
    rendered = response.body.decode()

    assert video.title in rendered
    assert 'name="category" type="checkbox" value="histoire"' in rendered
    assert 'name="category" type="checkbox" value="interview"' in rendered
    assert "--category-bg: #ff0066;" in rendered
    assert "--category-bg: #112233;" in rendered
    assert 'name="category" type="checkbox" value="cuisine"' not in rendered


def test_settings_api_updates_media_root_and_quota(tmp_path):
    db = make_session()

    result = api_routes.update_settings(
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

    result = api_routes.update_settings(
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

    result = api_routes.update_settings(
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

    assert video_library.video_list_state(video, {"is_completed": True}, False) == "watched"
    assert video_library.video_list_state(video, {"is_completed": False}, False) == "normal"
    assert video_library.video_list_state(video, None, False) == "normal"


def test_video_list_state_ignores_playback_for_replay_categories():
    video = Video(
        yt_video_id="ls-replay",
        title="Replay",
        url="https://youtube.com/watch?v=ls-replay",
        folder_path="/media/ls-replay",
    )

    assert video_library.video_list_state(video, {"is_completed": True}, True) == "normal"


def test_video_list_state_honours_manual_watched_even_on_replay_category():
    video = Video(
        yt_video_id="ls-manual",
        title="Manuel",
        url="https://youtube.com/watch?v=ls-manual",
        folder_path="/media/ls-manual",
        list_state="watched",
    )

    assert video_library.video_list_state(video, None, True) == "watched"


def test_video_list_state_unwatched_cancels_completed_playback():
    video = Video(
        yt_video_id="ls-unwatched",
        title="Non lu",
        url="https://youtube.com/watch?v=ls-unwatched",
        folder_path="/media/ls-unwatched",
        list_state="unwatched",
    )

    assert video_library.video_list_state(video, {"is_completed": True}, False) == "normal"


def test_video_list_state_hidden_wins_over_playback():
    video = Video(
        yt_video_id="ls-hidden",
        title="Écartée",
        url="https://youtube.com/watch?v=ls-hidden",
        folder_path="/media/ls-hidden",
        list_state="hidden",
    )

    assert video_library.video_list_state(video, {"is_completed": False}, False) == "hidden"


def test_set_video_list_state_persists_each_value():
    db = make_session()
    video = add_video(db)

    for state in ("watched", "unwatched", "hidden"):
        videos_routes.set_video_list_state(video.id, state, db)
        assert db.get(Video, video.id).list_state == state


def test_set_video_list_state_clear_resets_to_null():
    db = make_session()
    video = add_video(db)
    videos_routes.set_video_list_state(video.id, "hidden", db)

    response = videos_routes.set_video_list_state(video.id, "clear", db)

    assert db.get(Video, video.id).list_state is None
    assert json.loads(response.body.decode()) == {"state": None}


def test_set_video_list_state_rejects_unknown_value():
    db = make_session()
    video = add_video(db)

    with pytest.raises(HTTPException) as excinfo:
        videos_routes.set_video_list_state(video.id, "bogus", db)

    assert excinfo.value.status_code == 400


def test_set_video_list_state_rejects_unknown_video():
    db = make_session()

    with pytest.raises(HTTPException) as excinfo:
        videos_routes.set_video_list_state(9999, "hidden", db)

    assert excinfo.value.status_code == 404


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"hide_hidden=1",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

    assert hidden.title in rendered
    assert 'class="video-row video-row-hidden"' in rendered


def test_video_card_renders_list_state_buttons():
    db = make_session()
    video = add_video(db)
    video.list_state = "watched"
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

    assert f'data-list-state-toggle data-video-id="{video.id}"' in rendered
    assert 'data-list-state-target="watched"' in rendered
    assert 'data-list-state-target="hidden"' in rendered
    assert 'class="video-row video-row-watched"' in rendered
    assert "list-state-toggle-active" in rendered


def test_video_auto_list_state_reflects_playback_only():
    assert video_library.video_auto_list_state({"is_completed": True}, False) == "watched"
    assert video_library.video_auto_list_state({"is_completed": True}, True) == "normal"
    assert video_library.video_auto_list_state({"is_completed": False}, False) == "normal"
    assert video_library.video_auto_list_state(None, False) == "normal"


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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

    assert 'data-list-state="hidden" data-list-state-auto="watched"' in rendered


def test_list_state_buttons_are_icon_only_with_accessible_labels():
    db = make_session()
    add_video(db)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.videos_page(request, None, 1, db).body.decode()

    assert 'aria-label="Marquer comme vu"' in rendered
    assert 'aria-label="Écarter cette vidéo"' in rendered
    assert "list-state-icon" in rendered
    assert ">Lu</button>" not in rendered
    assert ">Écartée</button>" not in rendered


def resume_request():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/historique",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


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

    rendered = dashboard_routes.dashboard_history_page(resume_request(), 1, db).body.decode()

    assert f'data-list-state-toggle data-video-id="{video.id}"' in rendered
    assert 'aria-label="Marquer comme vu"' in rendered
    assert 'aria-label="Écarter cette vidéo"' in rendered


def test_resume_page_greys_hidden_video_more_strongly():
    db = make_session()
    video = add_video(db)
    video.list_state = "hidden"
    db.commit()
    add_playback_job(db, video)

    rendered = dashboard_routes.dashboard_history_page(resume_request(), 1, db).body.decode()

    assert 'class="dashboard-media-row video-card dashboard-media-row-hidden"' in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' not in rendered


def test_resume_page_greys_manually_watched_video():
    db = make_session()
    video = add_video(db)
    video.list_state = "watched"
    db.commit()
    add_playback_job(db, video)

    rendered = dashboard_routes.dashboard_history_page(resume_request(), 1, db).body.decode()

    assert 'class="dashboard-media-row video-card dashboard-media-row-completed"' in rendered
    assert 'class="dashboard-media-row video-card dashboard-media-row-hidden"' not in rendered


def test_resume_page_has_no_list_state_buttons_without_a_video():
    db = make_session()
    add_playback_job(db, None)

    rendered = dashboard_routes.dashboard_history_page(resume_request(), 1, db).body.decode()

    assert "data-list-state-toggle" not in rendered


def test_css_hides_progress_bar_inside_watched_and_hidden_rows():
    """Le serveur omet deja la barre quand la video est lue ; ces regles couvrent
    la bascule cote client, ou la ligne change de classe sans rechargement."""
    css = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app"
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
        / "app"
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert "retirés automatiquement du serveur" in rendered


def test_video_detail_has_no_purge_message_for_archived_video():
    db = make_session()
    video = add_video(db)
    video.video_path = None
    video.watched_at = datetime(2026, 6, 3, tzinfo=UTC)
    video.rating = 5
    db.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert "data-media-pager" in rendered
    assert 'data-initial="video"' in rendered
    # Nothing downloaded yet: both slides offer their download button.
    assert 'data-media-slide="video" data-state="idle"' in rendered
    assert 'data-media-slide="audio" data-state="idle"' in rendered
    assert rendered.count("data-media-download") == 2
    assert f'data-track-src="/videos/{video.id}/audio"' in rendered
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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/videos/{video.id}",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    rendered = videos_routes.video_detail_page(request, video.id, db).body.decode()

    assert 'data-initial="video"' in rendered
    assert 'data-media-slide="video" data-state="ready"' in rendered
    assert 'data-media-slide="audio" data-state="ready"' in rendered


def test_base_mini_player_is_one_link_to_the_audio_pane():
    base = (
        pathlib.Path(__file__).resolve().parent.parent / "app" / "templates" / "base.html"
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

    monkeypatch.setattr(videos_routes, "run_manual_download_job", fake_run)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/share-import",
            "headers": [(b"host", b"pt.lan:8000")],
            "scheme": "http",
            "server": ("pt.lan", 8000),
        }
    )

    response = videos_routes.share_import_video(request, url=" https://youtu.be/abc123 ", db=db)

    payload = json.loads(response.body)
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

    monkeypatch.setattr(videos_routes, "run_manual_download_job", fake_run)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/share-import",
            "headers": [],
            "scheme": "http",
            "server": ("pt.lan", 8000),
        }
    )

    failed = videos_routes.share_import_video(request, url="https://youtu.be/abc123", db=db)
    rejected = videos_routes.share_import_video(
        request, url="https://evil.test/watch?v=abc123", db=db
    )

    assert failed.status_code == 502
    assert json.loads(failed.body)["message"] == "Vidéo indisponible"
    assert rejected.status_code == 400
