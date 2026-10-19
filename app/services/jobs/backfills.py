"""Background catch-up jobs: channel profiles, view counts, transcripts, note index, thumbnails."""

import logging
import threading
import time

from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.services.channels.profile import (
    PROFILE_FETCH_DELAY_SECONDS,
    pending_profile_channel_ids,
    refresh_channel_profile,
)
from app.services.ingest.transcript_backfill import backfill_original_transcripts
from app.services.media.thumbnails import backfill_video_thumbnails
from app.services.rag.indexing import backfill_note_chunks
from app.services.youtube.view_counts import backfill_view_counts

# Held by the one running backfill sweep; see run_channel_profile_backfill_job.
_profile_backfill_lock = threading.Lock()

logger = logging.getLogger(__name__)


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
