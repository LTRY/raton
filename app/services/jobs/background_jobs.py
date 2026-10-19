import json
import logging
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.channels.profile import (
    PROFILE_FETCH_DELAY_SECONDS,
    pending_profile_channel_ids,
    refresh_channel_profile,
)
from app.services.ingest.media_import import (
    download_manual_media,
    import_video_metadata,
    retry_transcript_download,
)
from app.services.ingest.scanner import scan_channel_section
from app.services.ingest.transcript_backfill import backfill_original_transcripts
from app.services.llm.prompts import ANALYSIS_CLICKBAIT_HEADER, THUMBNAIL_MEDIA_TYPES
from app.services.llm.provider import AnthropicProvider, CompletionFailed, get_llm_provider
from app.services.llm.usage import compute_job_cost_usd
from app.services.media.thumbnails import backfill_video_thumbnails
from app.services.rag.indexing import backfill_note_chunks
from app.services.rag.library_chat_tools import (
    LIBRARY_CHAT_TOOLS,
    MAX_TOOL_TURNS,
    LibraryChatToolbox,
)
from app.services.youtube.view_counts import backfill_view_counts

logger = logging.getLogger(__name__)

# Held by the one running backfill sweep; see run_channel_profile_backfill_job.
_profile_backfill_lock = threading.Lock()

CHANNEL_VIDEO_PAGE_SIZE = 25
# How often a streaming `generate` job saves its text so far: short enough that
# the page polling it shows the résumé as it is written, long enough not to
# commit on every token.
PARTIAL_RESULT_INTERVAL_SECONDS = 0.4


@logged_job("manual_download")
def run_manual_download_job(
    job_id: int,
    video_url: str,
    media_types: list[str],
    download_transcript: bool,
    category_labels: str | None = None,
    subtitle_language: str | None = None,
    subtitle_source: str = "both",
    video_quality: str = "1080",
) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Téléchargement en cours..."
        db.commit()

        video = None
        subtitle_languages = [subtitle_language] if subtitle_language else None
        subtitle_source = subtitle_source if download_transcript else "none"
        for media_type in media_types:
            if media_type == "metadata":
                if video is None:
                    video = import_video_metadata(
                        db,
                        video_url,
                        subtitle_languages=subtitle_languages,
                        subtitle_source=subtitle_source,
                    )
                continue
            video = download_manual_media(
                db,
                video_url,
                media_type,
                download_transcript,
                subtitle_languages=subtitle_languages,
                subtitle_source=subtitle_source,
                video_quality=video_quality,
            )
        if video is None:
            raise ValueError("Aucun format à télécharger.")
        if category_labels is not None:
            video.category_labels = category_labels
            db.commit()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "downloaded"
            job.message = f"{video.title} a été téléchargé."
            job.video_id = video.id
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "failed"
            job.message = str(exc)
            db.commit()
    finally:
        db.close()


@logged_job("transcript_retry")
def run_transcript_retry_job(job_id: int, video_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Récupération du transcript en cours..."
        db.commit()

        video = db.get(Video, video_id)
        if video is None:
            raise ValueError("Vidéo introuvable.")
        video = retry_transcript_download(db, video)
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "downloaded"
            job.message = "Transcript récupéré."
            job.video_id = video.id
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "failed"
            job.message = str(exc)
            db.commit()
    finally:
        db.close()


@logged_job("channel_metadata_import")
def run_channel_metadata_import_job(
    job_id: int,
    channel_id: int,
    page: int = 1,
    section: str = "videos",
    mark_new: bool = False,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        channel = db.get(Channel, channel_id)
        if job is None:
            return
        if channel is None:
            job.status = "failed"
            job.message = "Chaîne introuvable."
            db.commit()
            return

        if job.status == "cancelled":
            return
        job.status = "running"
        section_label = "shorts" if section in {"short", "shorts"} else "vidéos"
        job.message = f"Import des métadonnées {section_label} de {channel.name} en cours..."
        db.commit()

        page = max(page, 1)
        scan_options = {
            "page": page,
            "page_size": CHANNEL_VIDEO_PAGE_SIZE,
            "max_pages": 1,
            "section": section,
        }
        if mark_new:
            scan_options["mark_new"] = True

        def should_stop() -> bool:
            # A column query reads the committed value; `db.get` would return the cached row.
            return (
                db.scalar(select(DownloadJob.status).where(DownloadJob.id == job_id)) == "cancelled"
            )

        imported = scan_channel_section(db, channel, should_stop=should_stop, **scan_options)
        job = db.get(DownloadJob, job_id)
        if job:
            db.refresh(job)
            plural = "s" if imported != 1 else ""
            if job.status == "cancelled":
                job.message = f"Exploration arrêtée : {imported} fiche{plural} {section_label} importée{plural} pour {channel.name}."
            else:
                job.status = "metadata"
                job.message = f"{imported} fiche{plural} {section_label} importée{plural} pour {channel.name}."
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job:
            job.status = "failed"
            job.message = f"Import des métadonnées échoué: {exc}"
            db.commit()
    finally:
        db.close()


@logged_job("channel_profile_refresh")
def run_channel_profile_refresh_job(channel_id: int) -> None:
    db = SessionLocal()
    try:
        channel = db.get(Channel, channel_id)
        if channel is not None:
            refresh_channel_profile(db, channel)
    finally:
        db.close()


@logged_job("view_count_backfill")
def run_view_count_backfill_job() -> None:
    """Startup catch-up: copy metadata.json view counts into `videos.view_count` (a no-op once done)."""
    db = SessionLocal()
    try:
        backfill_view_counts(db)
    except Exception:
        db.rollback()
        logger.exception("view count backfill failed")
    finally:
        db.close()


@logged_job("original_transcript_backfill")
def run_original_transcript_backfill_job() -> None:
    """Startup catch-up: fetch the original-language transcript of videos that lack one (a no-op once done)."""
    db = SessionLocal()
    try:
        backfill_original_transcripts(db)
    except Exception:
        db.rollback()
        logger.exception("original transcript backfill failed")
    finally:
        db.close()


@logged_job("note_index_backfill")
def run_note_index_backfill_job() -> None:
    """Startup catch-up: embed the notes of videos that have no chunk yet (a no-op once done)."""
    db = SessionLocal()
    try:
        backfill_note_chunks(db)
    except Exception:
        db.rollback()
        logger.exception("note index backfill failed")
    finally:
        db.close()


@logged_job("thumbnail_backfill")
def run_thumbnail_backfill_job() -> None:
    """Startup catch-up: create the stored thumbnail copies of videos that lack them (a no-op once done)."""
    db = SessionLocal()
    try:
        backfill_video_thumbnails(db)
    except Exception:
        db.rollback()
        logger.exception("thumbnail backfill failed")
    finally:
        db.close()


@logged_job("channel_profile_backfill")
def run_channel_profile_backfill_job() -> None:
    """Fetch the profile of every channel that has none yet, one at a time.

    Every way of adding a channel (form, CSV, API, library chat) and the startup
    catch-up share this single entry point instead of fetching on their own.
    Only one sweep runs at a time: a call made while another is running returns
    at once, because the running sweep re-queries the pending channels after
    each pass and so picks up the ones added meanwhile. Overlapping sweeps would
    double the YouTube calls and defeat the pause between channels.
    """
    if not _profile_backfill_lock.acquire(blocking=False):
        return
    try:
        db = SessionLocal()
        try:
            # A channel whose fetch fails stays pending; attempting it once per
            # run keeps the re-query loop from spinning on it forever.
            attempted: set[int] = set()
            first = True
            while True:
                channel_ids = [
                    cid for cid in pending_profile_channel_ids(db) if cid not in attempted
                ]
                if not channel_ids:
                    break
                for channel_id in channel_ids:
                    if not first:
                        time.sleep(PROFILE_FETCH_DELAY_SECONDS)
                    first = False
                    attempted.add(channel_id)
                    try:
                        channel = db.get(Channel, channel_id)
                        if channel is not None:
                            refresh_channel_profile(db, channel)
                    except Exception:
                        # E.g. the channel was deleted while its images downloaded:
                        # that must not abort the channels still waiting.
                        db.rollback()
                        logger.exception("Profil de la chaîne %s non récupéré", channel_id)
        finally:
            db.close()
    finally:
        _profile_backfill_lock.release()


@logged_job("llm")
def run_llm_job(job_id: int) -> None:
    """Run a direct-API completion for a queued LlmJob in the background."""
    added_channel_ids: list[int] = []
    db = SessionLocal()
    try:
        job = db.get(LlmJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()
        try:
            provider_instance = get_llm_provider()
            chunks: list[str] = []
            last_saved = time.monotonic()

            def save_partial_result(delta: str) -> None:
                nonlocal last_saved
                chunks.append(delta)
                if time.monotonic() - last_saved >= PARTIAL_RESULT_INTERVAL_SECONDS:
                    job.result = "".join(chunks)
                    db.commit()
                    last_saved = time.monotonic()

            if job.kind == "library_chat":

                def save_tool_calls(steps: list[dict]) -> None:
                    # Committed right away: the polling request reads it from another session.
                    job.tool_calls = json.dumps(steps)
                    db.commit()

                toolbox = LibraryChatToolbox(db, on_progress=save_tool_calls)
                added_channel_ids = toolbox.added_channel_ids
                completion = provider_instance.complete_with_tools(
                    job.prompt, LIBRARY_CHAT_TOOLS, toolbox.run, MAX_TOOL_TURNS
                )
                completion.text, sources = toolbox.extract_sources(completion.text)
                job.sources = json.dumps(sources)
            elif (
                job.kind == "generate"
                # The clickbait section is only ever requested in the prompt when the
                # user opted into attaching the thumbnail (see the include_image form
                # field on /transcript/generate) — checking for it here, rather than
                # recomputing video_analysis_has_image blindly, is what makes that
                # opt-out actually take effect instead of always attaching the image
                # whenever one happens to be available.
                and ANALYSIS_CLICKBAIT_HEADER in job.prompt
                and isinstance(provider_instance, AnthropicProvider)
                and job.video is not None
                and video_analysis_has_image(job.video, job.provider)
            ):
                image_path = local_media_path(job.video.thumbnail_path).resolve()
                media_type = THUMBNAIL_MEDIA_TYPES.get(image_path.suffix.lower(), "image/jpeg")
                completion = provider_instance.complete_with_image(
                    job.prompt, image_path.read_bytes(), media_type, on_text=save_partial_result
                )
            elif job.kind == "generate":
                completion = provider_instance.complete(job.prompt, on_text=save_partial_result)
            else:
                completion = provider_instance.complete(job.prompt)
            job.result = completion.text
            job.model = completion.model
            job.input_tokens = completion.input_tokens
            job.output_tokens = completion.output_tokens
            job.cost_usd = (
                completion.cost_usd
                if completion.cost_usd is not None
                else compute_job_cost_usd(
                    job.provider,
                    completion.model,
                    completion.input_tokens,
                    completion.output_tokens,
                )
            )
            job.status = "done"
        except Exception as exc:
            if isinstance(exc, CompletionFailed):
                # The API billed the tokens of a truncated/empty response even though the job failed.
                job.model = exc.usage.model
                job.input_tokens = exc.usage.input_tokens
                job.output_tokens = exc.usage.output_tokens
                job.cost_usd = exc.usage.cost_usd
            job.error = str(exc)
            job.status = "failed"
        job.completed_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()
    if added_channel_ids:
        # After the job is committed as done: the chat answer must not wait for the images.
        # Outside the try/finally so a failed job body never starts a long backfill with
        # its exception pending, and a backfill error cannot replace it.
        try:
            run_channel_profile_backfill_job()
        except Exception:
            logger.exception("Récupération des profils de chaînes échouée après le chat")


def video_analysis_has_image(video: Video, provider: str) -> bool:
    if provider != "anthropic" or not video.thumbnail_path or not video.folder_path:
        return False
    folder = local_media_path(video.folder_path).resolve()
    thumbnail = local_media_path(video.thumbnail_path).resolve()
    return thumbnail.is_file() and thumbnail.is_relative_to(folder)


def enqueue_llm_job(
    db: Session,
    *,
    kind: str,
    provider: str,
    video_id: int | None,
    prompt: str,
    question: str | None = None,
) -> LlmJob:
    job = LlmJob(
        kind=kind,
        provider=provider,
        video_id=video_id,
        prompt=prompt,
        question=question,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
