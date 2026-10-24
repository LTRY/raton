import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.video import Video
from back.services.common.job_log import log_job
from back.services.ingest import scan_events, throttle
from back.services.ingest.identity import canonical_video_url, video_known
from back.services.ingest.metadata_import import import_video_metadata
from back.services.ingest.throttle import (
    RateLimitedError,
    pause,
    pause_between_imports,
)
from back.services.media.storage import has_auto_download_headroom
from back.services.youtube.channel_info import list_channel_entries
from back.services.youtube.yt import is_not_yet_available_error, is_rate_limit_error

scan_lock = threading.Lock()
# YouTube answers HTTP 429 when yt-dlp hits it in a burst, and subtitles are the first thing it
# refuses. This bounds the load of one scan; the pauses between requests are in `throttle`.
MAX_IMPORTS_PER_SECTION = 10
logger = logging.getLogger(__name__)


def scan_channel(
    db: Session,
    channel: Channel,
    page: int = 1,
    page_size: int = 25,
    max_pages: int = 3,
    mark_new: bool = False,
    max_imports: int | None = None,
) -> int:
    return scan_channel_section(
        db,
        channel,
        page=page,
        page_size=page_size,
        max_pages=max_pages,
        section="videos",
        mark_new=mark_new,
        max_imports=max_imports,
    )


def scan_channel_section(
    db: Session,
    channel: Channel,
    page: int = 1,
    page_size: int = 25,
    max_pages: int = 3,
    section: str = "videos",
    mark_new: bool = False,
    max_imports: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    skip_known: bool = False,
) -> int:
    """Import the metadata of the channel's new videos and return how many were imported.

    Listing and importing are two phases so `max_imports` can leave a backlog for the next scan:
    the entries to import are collected first, then imported oldest first. The leftovers are then
    the newest ones, still ahead of the first known video, so the next scan finds them again.
    Importing newest first would strand them behind a known video.

    `skip_known` keeps going past a video already in the DB instead of stopping there: the explore
    button asks for a page of the listing that may start with videos imported earlier.

    Raises RateLimitedError (after logging it) when YouTube answers 429; what was imported before
    stays imported.
    """
    is_shorts = section in {"short", "shorts"}
    section_label = "shorts" if is_shorts else "vidéos"
    start_page = max(page, 1)
    max_pages = max(max_pages, 1)

    pending: list[dict] = []
    pending_ids: set[str] = set()
    for current_page in range(start_page, start_page + max_pages):
        try:
            entries = list_channel_entries(
                channel, page=current_page, page_size=page_size, section=section
            )
        except Exception as exc:
            log_job(db, "failed", f"Failed to list channel: {exc}", channel_id=channel.id)
            scan_events.emit(
                f"{channel.name} ({section_label}) : lecture de la chaîne impossible ({exc}).",
                "error",
            )
            if is_rate_limit_error(exc):
                raise RateLimitedError(str(exc)) from exc
            break
        if not entries:
            break

        reached_known = False
        new_on_page = 0
        for entry in entries:
            yt_video_id = entry.get("id")
            if not yt_video_id:
                continue
            if video_known(db, yt_video_id):
                if is_shorts:
                    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
                    if existing and "/shorts/" not in existing.url:
                        existing.url = canonical_video_url(existing.url, yt_video_id, "shorts")
                        db.add(existing)
                        db.commit()
                    continue
                if skip_known:
                    continue
                reached_known = True
                break
            # A feed that shifts between two page requests can repeat an entry.
            if yt_video_id not in pending_ids:
                pending_ids.add(yt_video_id)
                pending.append(entry)
            new_on_page += 1
        # Shorts do not stop at a known one (their old URLs get repaired above), so a page with
        # nothing new is what tells that the rest of the feed is already imported.
        if reached_known or (is_shorts and new_on_page == 0):
            break

    if max_imports is not None and len(pending) > max_imports:
        scan_events.emit(
            f"{channel.name} ({section_label}) : {len(pending)} nouveautés, {max_imports} importées maintenant, "
            "le reste aux prochains scans."
        )
    elif pending:
        scan_events.emit(
            f"{channel.name} ({section_label}) : {len(pending)} nouveauté(s) à importer."
        )
    if max_imports is not None:
        pending = list(reversed(pending))[:max_imports]

    imported = 0
    for entry in pending:
        # Asked by the person (the X of the exploration bubble): what was imported stays imported.
        if should_stop is not None and should_stop():
            break
        yt_video_id = entry["id"]
        title = entry.get("title") or yt_video_id
        video_url = entry.get("url") or f"https://www.youtube.com/watch?v={yt_video_id}"
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={yt_video_id}"
        if imported:
            pause_between_imports()
        try:
            video = import_video_metadata(
                db,
                video_url,
                channel.id,
                preview=entry,
                download_source="auto",
                source_section=section,
                is_new=mark_new,
            )
            log_job(
                db,
                "metadata",
                f"Imported metadata for {video.title}",
                channel_id=channel.id,
                video_id=video.id,
            )
            scan_events.emit(f"{channel.name} : « {video.title} » importée.")
            imported += 1
        except RateLimitedError as exc:
            db.rollback()
            log_job(
                db, "failed", f"Failed to import metadata for {title}: {exc}", channel_id=channel.id
            )
            raise
        except Exception as exc:
            db.rollback()
            if is_not_yet_available_error(exc):
                # A scheduled premiere/live is listed before it exists: not a failure, the next
                # scan imports it once it is out.
                log_job(
                    db,
                    "scheduled",
                    f"« {title} » est programmée et pas encore disponible, reprise au prochain scan.",
                    channel_id=channel.id,
                )
                scan_events.emit(
                    f"{channel.name} : « {title} » n'est pas encore sortie (première), reprise plus tard."
                )
                continue
            log_job(
                db, "failed", f"Failed to import metadata for {title}: {exc}", channel_id=channel.id
            )
            scan_events.emit(f"{channel.name} : échec de l'import de « {title} » ({exc}).", "error")

    return imported


def run_scan(db: Session, enforce_storage_headroom: bool = False) -> dict[str, int | str]:
    if not scan_lock.acquire(blocking=False):
        scan_events.emit("Un scan est déjà en cours.", "error", final=True)
        return {"status": "already_running", "downloaded": 0, "deleted": 0}
    try:
        if enforce_storage_headroom and not has_auto_download_headroom(db):
            log_job(
                db,
                "skipped",
                "Scan automatique ignoré: moins de 20% du quota global est disponible.",
            )
            scan_events.emit(
                "Scan ignoré : moins de 20 % du quota de stockage est disponible.",
                "error",
                final=True,
            )
            return {"status": "storage_low", "downloaded": 0, "deleted": 0}
        imported = 0
        followed = Channel.auto_metadata_enabled.is_(True) | Channel.auto_shorts_enabled.is_(True)
        # Least recently scanned first: a scan stopped by a rate limit resumes where it stopped.
        channels = db.scalars(
            select(Channel)
            .where(followed)
            .order_by(Channel.last_scanned_at.asc().nulls_first(), Channel.id)
        ).all()
        started = time.monotonic()
        scan_events.emit(f"Scan démarré : {len(channels)} chaîne(s) suivie(s).")
        previous_imported = None
        try:
            for index, channel in enumerate(channels, start=1):
                if previous_imported is not None:
                    # Read through the module so tests can zero the pauses.
                    pause(
                        throttle.PAUSE_BETWEEN_CHANNELS
                        if previous_imported
                        else throttle.PAUSE_AFTER_LISTING_ONLY
                    )
                scan_events.emit(f"Chaîne {index}/{len(channels)} : {channel.name}…")
                channel_imported = 0
                if channel.auto_metadata_enabled:
                    channel_imported += scan_channel(
                        db, channel, mark_new=True, max_imports=MAX_IMPORTS_PER_SECTION
                    )
                if channel.auto_shorts_enabled:
                    channel_imported += scan_channel_section(
                        db,
                        channel,
                        section="shorts",
                        mark_new=True,
                        max_imports=MAX_IMPORTS_PER_SECTION,
                    )
                channel.last_scanned_at = datetime.now(UTC)
                db.add(channel)
                db.commit()
                imported += channel_imported
                previous_imported = channel_imported
                if not channel_imported:
                    scan_events.emit(f"{channel.name} : rien de nouveau.")
        except RateLimitedError:
            # The channels not reached yet come first in tomorrow's scan (see last_scanned_at).
            log_job(
                db,
                "warning",
                "Scan automatique interrompu: YouTube limite les requêtes (HTTP 429).",
            )
            scan_events.emit(
                f"Scan interrompu : YouTube limite les requêtes (HTTP 429). {imported} fiche(s) importée(s) ; "
                "la suite reprendra au prochain scan.",
                "error",
                final=True,
            )
            return {"status": "rate_limited", "downloaded": imported, "deleted": 0}
        elapsed = int(time.monotonic() - started)
        scan_events.emit(
            f"Scan terminé : {imported} fiche(s) importée(s) en {elapsed} s.", final=True
        )
        return {"status": "completed", "downloaded": imported, "deleted": 0}
    finally:
        scan_lock.release()
