"""One-shot catch-up: give a transcript to the videos that lack one although an original track exists.

Until the scan stopped asking for machine-translated tracks (YouTube answers 429 to those), a video
whose `fr`/`en` request failed was imported without transcript even when its original-language
captions were available. metadata.json keeps the track list, so the candidates are found without
any request; only those get one.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.models.video import TranscriptStatus, Video
from app.services import scan_events
from app.services.scanner import log_job, pause_between_imports, retry_transcript_download
from app.services.settings import get_setting, set_setting
from app.services.yt import choose_subtitle_track

logger = logging.getLogger(__name__)

BACKFILL_DONE_KEY = "original_transcript_backfill_done"
# Stop instead of grinding through the whole library when requests keep failing.
MAX_CONSECUTIVE_FAILURES = 5


def has_original_track(video: Video) -> bool:
    if not video.metadata_path:
        return False
    try:
        data = json.loads(local_media_path(video.metadata_path).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return isinstance(data, dict) and choose_subtitle_track(data) is not None


def backfill_original_transcripts(db: Session) -> int:
    """Fetch the missing transcripts that have a track; returns how many were recovered.

    Marked done only when every candidate was tried, so an interruption resumes at the next startup.
    """
    if get_setting(db, BACKFILL_DONE_KEY, "") == "true":
        return 0
    candidates = [
        video
        for video in db.scalars(
            select(Video)
            .where(
                Video.transcript_status == TranscriptStatus.missing,
                Video.metadata_path.is_not(None),
            )
            .order_by(Video.id)
        )
        if has_original_track(video)
    ]
    recovered = 0
    failures = 0
    for index, video in enumerate(candidates):
        if index:
            pause_between_imports()
        try:
            retry_transcript_download(db, video)
        except Exception as exc:
            db.rollback()
            failures += 1
            log_job(
                db,
                "warning",
                f"Transcript non récupéré pour « {video.title} »: {exc}",
                video_id=video.id,
            )
            if failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("original transcript backfill stopped after %d failures", failures)
                return recovered
            continue
        failures = 0
        recovered += 1
        log_job(
            db,
            "downloaded",
            f"Transcript récupéré (piste originale) : {video.title}",
            video_id=video.id,
        )
    set_setting(db, BACKFILL_DONE_KEY, "true")
    db.commit()
    if candidates:
        scan_events.emit(f"Transcripts rattrapés : {recovered} sur {len(candidates)}.")
    return recovered
