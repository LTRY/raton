"""Nightly generation of structured notes + short résumé for the videos that have none.

One sweep per night (scheduler.py), in two steps that survive a restart of the app because the
work itself runs on Anthropic's side, as a Message Batch (half price):

1. collect the batch submitted by the previous sweep and apply each result (notes file, résumé
   file, embeddings);
2. submit a new batch of at most BATCH_SIZE eligible videos.

The batch id lives in app_settings, one batch at a time. Each submitted video has an `auto_notes`
LlmJob, `running` while the batch is out, then `applied` or `failed`: that is what "Coûts LLM" in
/settings reads, and what caps the retries of a video that keeps failing.

The notes are what the cross-video search indexes (docs/spec/19-indexation-et-recherche-notes.md);
the long résumé, the questions and the analysis stay on the robot button.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings, local_media_path
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.embeddings import EmbeddingError
from app.services.llm import (
    AnthropicProvider,
    BatchEntry,
    build_auto_notes_prompt,
    get_llm_provider,
    split_auto_notes_result,
    split_notes_sections,
)
from app.services.rag_indexing import (
    NOTES_FILE_NAME,
    SUMMARY_SHORT_FILE_NAME,
    backfill_note_chunks,
    backfill_summary_chunks,
    index_video_notes,
)
from app.services.settings import (
    get_auto_notes_enabled,
    get_auto_notes_excluded_category_labels,
    get_setting,
    parse_video_category_labels,
    set_setting,
)

logger = logging.getLogger(__name__)

AUTO_NOTES_KIND = "auto_notes"
BATCH_SIZE = 100
# A video whose requests keep failing (too long, refused...) is left alone: a truncated answer is billed.
MAX_FAILURES_PER_VIDEO = 3
# Shorter than this there is nothing to take notes on (cut subtitles, a jingle).
MIN_TRANSCRIPT_CHARS = 500
# Anthropic expires a batch after 24 hours; past this the batch is given up on and its videos retried.
BATCH_STALE_AFTER = timedelta(hours=36)
FAILURES_BEFORE_SKIPPING_A_NIGHT = 3

BATCH_ID_KEY = "auto_notes_batch_id"
BATCH_SUBMITTED_AT_KEY = "auto_notes_batch_submitted_at"
LAST_RUN_AT_KEY = "auto_notes_last_run_at"
LAST_RUN_SUMMARY_KEY = "auto_notes_last_run_summary"

_sweep_lock = threading.Lock()


@dataclass
class SweepResult:
    collected: int = 0  # results applied
    failed: int = 0
    submitted: int = 0
    summaries_indexed: int = 0
    status: str = "ok"

    def describe(self) -> str:
        parts = []
        if self.collected or self.failed:
            parts.append(f"{self.collected} appliquée(s), {self.failed} en échec")
        if self.submitted:
            parts.append(f"{self.submitted} soumise(s)")
        if self.summaries_indexed:
            parts.append(f"{self.summaries_indexed} résumé(s) indexé(s)")
        return " · ".join(parts) or self.status


def _notes_path(video: Video):
    return local_media_path(video.transcript_path).with_name(NOTES_FILE_NAME)


def effective_labels(own_raw: str | None, channel_raw: str | None) -> set[str]:
    """The video's own labels, or its channel's when it has none (the rule used everywhere else)."""
    own = parse_video_category_labels(own_raw)
    return set(own or parse_video_category_labels(channel_raw))


def in_flight_video_ids(db: Session) -> set[int]:
    return set(
        db.scalars(
            select(LlmJob.video_id).where(
                LlmJob.kind == AUTO_NOTES_KIND, LlmJob.status == "running"
            )
        )
    )


def failure_counts(db: Session) -> dict[int, int]:
    """Failed attempts per video id."""
    return dict(
        db.execute(
            select(LlmJob.video_id, func.count(LlmJob.id))
            .where(LlmJob.kind == AUTO_NOTES_KIND, LlmJob.status == "failed")
            .group_by(LlmJob.video_id)
        ).all()
    )


def candidate_order():
    """Most recent first: the order videos are picked in, shared with the /rag page's "next batch" list."""
    return (
        desc(func.coalesce(Video.published_at, Video.downloaded_at, Video.created_at)),
        desc(Video.id),
    )


def skip_reason(
    video_id: int,
    url: str,
    labels: set[str],
    excluded: set[str],
    in_flight: set[int],
    failures: dict[int, int],
) -> str | None:
    """Why a video is left out of the batches (database facts only), or None when it can be taken.

    The transcript's size and the notes file are checked on disk by `eligible_videos`, at submission.
    """
    if video_id in in_flight:
        return "in_batch"
    if failures.get(video_id, 0) >= MAX_FAILURES_PER_VIDEO:
        return "failed"
    if "/shorts/" in url:
        return "short"
    if labels & excluded:
        return "label"
    return None


def eligible_videos(db: Session, limit: int) -> list[Video]:
    """Up to `limit` videos to take notes on, most recent first.

    Eligible: a readable transcript, no notes yet, not a short, no excluded label, not already in a
    batch, and fewer than MAX_FAILURES_PER_VIDEO failed attempts.
    """
    excluded = set(get_auto_notes_excluded_category_labels(db))
    in_flight = in_flight_video_ids(db)
    failures = failure_counts(db)
    candidates = db.scalars(
        select(Video)
        .where(Video.transcript_path.is_not(None), Video.transcript_path != "")
        .options(selectinload(Video.channel))
        .order_by(*candidate_order())
    )
    selected: list[Video] = []
    for video in candidates:
        if len(selected) >= limit:
            break
        channel_labels = video.channel.category_labels if video.channel else None
        labels = effective_labels(video.category_labels, channel_labels)
        if skip_reason(video.id, video.url, labels, excluded, in_flight, failures):
            continue
        try:
            if (
                _notes_path(video).exists()
                or local_media_path(video.transcript_path).stat().st_size < MIN_TRANSCRIPT_CHARS
            ):
                continue
        except OSError:
            continue
        selected.append(video)
    return selected


def submit_batch(db: Session, provider: AnthropicProvider, limit: int | None = None) -> int:
    """Create one running LlmJob per eligible video and send them as a batch; returns how many."""
    videos = eligible_videos(db, limit or BATCH_SIZE)
    jobs: list[tuple[LlmJob, str]] = []
    for video in videos:
        try:
            transcript = local_media_path(video.transcript_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        # The prompt is not stored: it holds the whole transcript, and the batch keeps its own copy.
        job = LlmJob(
            kind=AUTO_NOTES_KIND,
            provider="anthropic",
            video_id=video.id,
            prompt=f"auto_notes:{video.id}",
            status="running",
        )
        db.add(job)
        jobs.append((job, build_auto_notes_prompt(transcript)))
    if not jobs:
        return 0
    db.flush()
    try:
        batch_id = provider.submit_batch({f"job-{job.id}": prompt for job, prompt in jobs})
    except Exception:
        db.rollback()
        raise
    set_setting(db, BATCH_ID_KEY, batch_id)
    set_setting(db, BATCH_SUBMITTED_AT_KEY, datetime.now(UTC).isoformat())
    db.commit()
    return len(jobs)


def _apply_entry(db: Session, job: LlmJob, entry: BatchEntry) -> bool:
    """Write one successful result to disk and index it; False (job failed) when it holds no notes."""
    video = db.get(Video, job.video_id) if job.video_id else None
    if video is None or not video.transcript_path:
        job.status, job.error = "failed", "Vidéo ou transcript introuvable."
        return False
    notes_text, summary_short = split_auto_notes_result(entry.text or "")
    if not split_notes_sections(notes_text):
        job.status, job.error = "failed", "La réponse ne contient aucune note exploitable."
        return False
    notes_path = _notes_path(video)
    notes_path.write_text(notes_text, encoding="utf-8")
    # A résumé the user already generated by hand is theirs; never overwritten by a lighter one.
    summary_path = notes_path.with_name(SUMMARY_SHORT_FILE_NAME)
    if summary_short and not summary_path.exists():
        summary_path.write_text(summary_short, encoding="utf-8")
    job.status = "applied"
    try:
        index_video_notes(video.id, notes_text, summary_short or None)
    except EmbeddingError as exc:
        # The notes are saved; backfill_note_chunks indexes them on a later sweep or at startup.
        logger.warning("Notes de la vidéo %s écrites mais non indexées : %s", video.id, exc)
    return True


def collect_batch(
    db: Session, provider: AnthropicProvider, batch_id: str, result: SweepResult
) -> bool:
    """Apply the results of `batch_id` if it has ended; returns True when the batch is settled (or lost)."""
    submitted_raw = get_setting(db, BATCH_SUBMITTED_AT_KEY, "")
    entries = provider.batch_results(batch_id)
    if entries is None:
        submitted = datetime.fromisoformat(submitted_raw) if submitted_raw else None
        if submitted is None or datetime.now(UTC) - submitted <= BATCH_STALE_AFTER:
            return False
        logger.warning("Lot de notes %s sans réponse depuis plus de 36 h : abandonné.", batch_id)
        entries = []
    running = {
        f"job-{job.id}": job
        for job in db.scalars(
            select(LlmJob).where(LlmJob.kind == AUTO_NOTES_KIND, LlmJob.status == "running")
        )
    }
    now = datetime.now(UTC)
    for entry in entries:
        job = running.pop(entry.custom_id, None)
        if job is None:
            continue
        job.model, job.input_tokens, job.output_tokens, job.cost_usd = (
            entry.model,
            entry.input_tokens,
            entry.output_tokens,
            entry.cost_usd,
        )
        job.completed_at = now
        if entry.text is None:
            job.status, job.error = "failed", entry.error
            result.failed += 1
            continue
        job.result = entry.text
        try:
            applied = _apply_entry(db, job, entry)
        except Exception as exc:
            logger.exception("Application des notes de la vidéo %s échouée", job.video_id)
            job.status, job.error, applied = "failed", str(exc), False
        result.collected += applied
        result.failed += not applied
    for job in running.values():
        # In flight but absent from the batch's results (or the batch was abandoned): retried later.
        job.status, job.error, job.completed_at = "failed", "Absente des résultats du lot.", now
        result.failed += 1
    set_setting(db, BATCH_ID_KEY, "")
    set_setting(db, BATCH_SUBMITTED_AT_KEY, "")
    db.commit()
    return True


def run_auto_notes_sweep(db: Session, provider: AnthropicProvider | None = None) -> SweepResult:
    """One nightly pass: collect the previous batch, index what lacks a chunk, submit the next batch."""
    result = SweepResult()
    if not _sweep_lock.acquire(blocking=False):
        result.status = "déjà en cours"
        return result
    try:
        if not get_auto_notes_enabled(db):
            result.status = "désactivé"
            return result
        if provider is None:
            if not get_settings().anthropic_api_key:
                result.status = "clé Anthropic absente"
                return result
            provider = get_llm_provider()
            if not isinstance(provider, AnthropicProvider):
                result.status = "fournisseur sans lots"
                return result
        batch_id = get_setting(db, BATCH_ID_KEY, "")
        if batch_id and not collect_batch(db, provider, batch_id, result):
            result.status = "lot en cours"
            return result
        # Notes written while the embedding API was down, and résumés of videos indexed before
        # résumés were: no LLM call, only embeddings; each stops at the first API failure.
        backfill_note_chunks(db)
        result.summaries_indexed = backfill_summary_chunks(db)
        if result.collected == 0 and result.failed >= FAILURES_BEFORE_SKIPPING_A_NIGHT:
            # The whole batch just collected failed: an API or account problem rather than the videos'.
            # Skip tonight's submission; the next sweep tries again with nothing pending.
            result.status = "pause : le dernier lot a échoué"
            return result
        result.submitted = submit_batch(db, provider)
        return result
    finally:
        try:
            set_setting(db, LAST_RUN_AT_KEY, datetime.now(UTC).isoformat())
            set_setting(db, LAST_RUN_SUMMARY_KEY, result.describe())
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Enregistrement du dernier passage des notes automatiques échoué")
        _sweep_lock.release()
