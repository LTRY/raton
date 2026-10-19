import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import log_event, logged_job
from app.db.session import SessionLocal
from app.services.background_jobs import (
    run_channel_profile_backfill_job,
    run_note_index_backfill_job,
    run_original_transcript_backfill_job,
    run_thumbnail_backfill_job,
    run_view_count_backfill_job,
)
from app.services.channels.scanner import run_scan
from app.services.media.media_storage import purge_watched_media
from app.services.rag.auto_notes import (
    DAILY_AUTO_NOTES_HOUR,
    run_auto_notes_sweep,
)
from app.services.rag.auto_notes import (
    LAST_RUN_AT_KEY as AUTO_NOTES_LAST_RUN_AT_KEY,
)
from app.services.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Europe/Paris")
SCAN_JOB_ID = "scan_channels"
SCAN_CATCHUP_JOB_ID = "scan_channels_catchup"
DAILY_SCAN_HOUR = 3
CATCH_UP_STALE_AFTER = timedelta(hours=24)
PROFILE_BACKFILL_JOB_ID = "backfill_channel_profiles"
VIEW_COUNT_BACKFILL_JOB_ID = "backfill_view_counts"
THUMBNAIL_BACKFILL_JOB_ID = "backfill_thumbnails"
NOTE_INDEX_BACKFILL_JOB_ID = "backfill_note_index"
TRANSCRIPT_BACKFILL_JOB_ID = "backfill_original_transcripts"

LAST_AUTO_SCAN_AT_KEY = "last_auto_scan_at"
LAST_AUTO_SCAN_STATUS_KEY = "last_auto_scan_status"
LAST_AUTO_SCAN_IMPORTED_KEY = "last_auto_scan_imported_count"

MEDIA_PURGE_JOB_ID = "purge_media"
MEDIA_PURGE_CATCHUP_JOB_ID = "purge_media_catchup"
DAILY_MEDIA_PURGE_HOUR = 4
# Stored in app_settings under its old name: renaming it would make the startup catch-up purge run once more.
LAST_MEDIA_PURGE_AT_KEY = "last_media_cache_cleanup_at"

AUTO_NOTES_JOB_ID = "auto_notes_sweep"
AUTO_NOTES_CATCHUP_JOB_ID = "auto_notes_sweep_catchup"


def record_scan_result(db: Session, result: dict) -> None:
    set_setting(db, LAST_AUTO_SCAN_AT_KEY, datetime.now(UTC).isoformat())
    set_setting(db, LAST_AUTO_SCAN_STATUS_KEY, str(result.get("status", "")))
    set_setting(db, LAST_AUTO_SCAN_IMPORTED_KEY, str(result.get("downloaded", 0)))
    db.commit()


def get_last_auto_scan_info(db: Session) -> dict:
    at_raw = get_setting(db, LAST_AUTO_SCAN_AT_KEY, "")
    return {
        "at": datetime.fromisoformat(at_raw) if at_raw else None,
        "status": get_setting(db, LAST_AUTO_SCAN_STATUS_KEY, "") or None,
        "imported": int(get_setting(db, LAST_AUTO_SCAN_IMPORTED_KEY, "0")),
    }


def record_media_purge(db: Session, now: datetime | None = None) -> None:
    set_setting(db, LAST_MEDIA_PURGE_AT_KEY, (now or datetime.now(UTC)).isoformat())
    db.commit()


def get_last_media_purge_at(db: Session) -> datetime | None:
    raw = get_setting(db, LAST_MEDIA_PURGE_AT_KEY, "")
    return datetime.fromisoformat(raw) if raw else None


def scan_is_overdue(
    last_scan_at: datetime | None,
    *,
    now: datetime | None = None,
    stale_after: timedelta = CATCH_UP_STALE_AFTER,
) -> bool:
    if last_scan_at is None:
        return True
    now = now or datetime.now(UTC)
    return now - last_scan_at > stale_after


@logged_job("scheduled_scan")
def scheduled_scan() -> None:
    db = SessionLocal()
    try:
        result = run_scan(db, enforce_storage_headroom=True)
        record_scan_result(db, result)
    finally:
        db.close()


@logged_job("scheduled_media_purge")
def scheduled_media_purge() -> None:
    db = SessionLocal()
    try:
        purge_watched_media(db)
        record_media_purge(db)
    finally:
        db.close()


@logged_job("scheduled_auto_notes")
def scheduled_auto_notes() -> None:
    db = SessionLocal()
    try:
        run_auto_notes_sweep(db)
    except Exception:
        db.rollback()
        logger.exception("auto notes sweep failed")
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    # Opt-out for instances that must stay inert: PR previews and a dev PC sharing a database.
    if not get_settings().scheduler_enabled:
        log_event(logger, "scheduler.disabled", reason="APP_SCHEDULER_ENABLED")
        return
    scheduler.add_job(
        scheduled_scan,
        CronTrigger(hour=DAILY_SCAN_HOUR, minute=0, timezone="Europe/Paris"),
        id=SCAN_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_media_purge,
        CronTrigger(hour=DAILY_MEDIA_PURGE_HOUR, minute=0, timezone="Europe/Paris"),
        id=MEDIA_PURGE_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_auto_notes,
        CronTrigger(hour=DAILY_AUTO_NOTES_HOUR, minute=0, timezone="Europe/Paris"),
        id=AUTO_NOTES_JOB_ID,
        replace_existing=True,
    )
    db = SessionLocal()
    try:
        overdue = scan_is_overdue(get_last_auto_scan_info(db)["at"])
        cleanup_overdue = scan_is_overdue(get_last_media_purge_at(db))
        last_notes_raw = get_setting(db, AUTO_NOTES_LAST_RUN_AT_KEY, "")
        notes_overdue = scan_is_overdue(
            datetime.fromisoformat(last_notes_raw) if last_notes_raw else None
        )
    finally:
        db.close()
    log_event(
        logger,
        "scheduler.catchup_check",
        scan_overdue=overdue,
        purge_overdue=cleanup_overdue,
        notes_overdue=notes_overdue,
    )
    if overdue:
        # No trigger: APScheduler runs this once, as soon as possible, on its own
        # background thread — doesn't block FastAPI startup. Catches up on a scan
        # that a fixed 3am cron would otherwise silently miss if the machine (or
        # the Docker VM) wasn't running at that exact time.
        scheduler.add_job(scheduled_scan, id=SCAN_CATCHUP_JOB_ID, replace_existing=True)
    if cleanup_overdue:
        # Same catch-up idea as the scan above, for the 4am media purge.
        scheduler.add_job(
            scheduled_media_purge, id=MEDIA_PURGE_CATCHUP_JOB_ID, replace_existing=True
        )
    if notes_overdue:
        # Same catch-up as above for the 5am notes sweep: its batch is collected on the next run.
        scheduler.add_job(scheduled_auto_notes, id=AUTO_NOTES_CATCHUP_JOB_ID, replace_existing=True)
    # Channels added while the app was down, or before profiles existed, have no
    # profile yet. A no-op when none is pending.
    scheduler.add_job(
        run_channel_profile_backfill_job, id=PROFILE_BACKFILL_JOB_ID, replace_existing=True
    )
    scheduler.add_job(
        run_view_count_backfill_job, id=VIEW_COUNT_BACKFILL_JOB_ID, replace_existing=True
    )
    scheduler.add_job(
        run_thumbnail_backfill_job, id=THUMBNAIL_BACKFILL_JOB_ID, replace_existing=True
    )
    scheduler.add_job(
        run_note_index_backfill_job, id=NOTE_INDEX_BACKFILL_JOB_ID, replace_existing=True
    )
    scheduler.add_job(
        run_original_transcript_backfill_job, id=TRANSCRIPT_BACKFILL_JOB_ID, replace_existing=True
    )
    scheduler.start()
    log_event(
        logger,
        "scheduler.started",
        daily_jobs=",".join([SCAN_JOB_ID, MEDIA_PURGE_JOB_ID, AUTO_NOTES_JOB_ID]),
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log_event(logger, "scheduler.stopped")
