import json
import logging
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.core.logging import log_event
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import TranscriptStatus, Video
from app.services import scan_events
from app.services.audio_extract import copy_audio_track, extractable_video_file
from app.services.files import directory_size, move_directory, remove_directory, unique_sibling_path
from app.services.settings import get_media_root, get_sponsor_segment_categories
from app.services.sponsor_segments import replace_video_sponsor_segments
from app.services.sponsorblock import fetch_sponsorblock_segments
from app.services.storage import has_auto_download_headroom
from app.services.thumbnails import ensure_video_thumbnails
from app.services.url_guard import ensure_public_http_url
from app.services.view_counts import parse_duration_seconds, parse_view_count
from app.services.yt import (
    SUBTITLE_EXTENSIONS,
    build_video_folder,
    discover_downloaded_files,
    download_media,
    download_subtitles,
    download_thumbnail,
    extract_video_info,
    is_not_yet_available_error,
    is_rate_limit_error,
    list_channel_entries,
    parse_yt_date,
    write_metadata,
    write_transcript,
)

scan_lock = threading.Lock()

# YouTube answers HTTP 429 when yt-dlp hits it in a burst, and subtitles are the first thing it
# refuses. These bound the load of one scan; the pauses (min, max seconds) are module-level so
# tests can zero them.
MAX_IMPORTS_PER_SECTION = 10
logger = logging.getLogger(__name__)

PAUSE_BETWEEN_IMPORTS = (2.0, 5.0)
PAUSE_BETWEEN_CHANNELS = (10.0, 30.0)
# After a channel that only needed a listing (nothing imported): one light request, no need to wait long.
PAUSE_AFTER_LISTING_ONLY = (1.0, 3.0)


class RateLimitedError(Exception):
    """YouTube is throttling us: the caller should stop issuing requests, not retry the next item."""


def pause(bounds: tuple[float, float]) -> None:
    low, high = bounds
    if high > 0:
        time.sleep(random.uniform(low, high))


def pause_between_imports() -> None:
    pause(PAUSE_BETWEEN_IMPORTS)


JOB_STATUS_LOG_LEVELS = {
    "failed": logging.ERROR,
    "warning": logging.WARNING,
    "skipped": logging.WARNING,
}


def video_already_downloaded(db: Session, yt_video_id: str) -> bool:
    return db.scalar(select(Video.id).where(Video.yt_video_id == yt_video_id)) is not None


def log_job(
    db: Session,
    status: str,
    message: str,
    channel_id: int | None = None,
    video_id: int | None = None,
) -> DownloadJob:
    job = DownloadJob(channel_id=channel_id, video_id=video_id, status=status, message=message)
    db.add(job)
    db.commit()
    # Mirror every `/logs` row into the journal; a playback row carries a JSON payload, not text.
    log_event(
        logger,
        "job.record",
        level=JOB_STATUS_LOG_LEVELS.get(status, logging.INFO),
        status=status,
        message="" if status == "played" else message,
        channel_id=channel_id,
        video_id=video_id,
    )
    return job


def record_playback_activity(
    db: Session,
    video: Video,
    media_type: str,
    position_seconds: float,
    duration_seconds: float,
    watched_seconds: float,
) -> DownloadJob:
    """Log a playback activity job, used by the web /activity route.

    The dashboard's "Historique" section and playback-time stats both read this
    back via app.web.playback.playback_activity_view, which expects this exact JSON shape.
    """
    position_seconds = max(position_seconds, 0)
    duration_seconds = max(duration_seconds, 0)
    watched_seconds = max(watched_seconds, 0)
    action = "Reprise" if position_seconds >= 3 else "Lecture"
    media_label = "audio" if media_type == "audio" else "vidéo"
    return log_job(
        db,
        "played",
        json.dumps(
            {
                "type": "playback",
                "action": action,
                "media_label": media_label,
                "position_seconds": position_seconds,
                "duration_seconds": duration_seconds,
                "watched_seconds": watched_seconds,
                "title": video.title,
            },
            ensure_ascii=False,
        ),
        channel_id=video.channel_id,
        video_id=video.id,
    )


def staged_folder(final_folder: Path) -> Path:
    return unique_sibling_path(final_folder, "download")


def final_path(path: Path | None, staging: Path, final_folder: Path) -> Path | None:
    if path is None:
        return None
    return final_folder / path.relative_to(staging)


def commit_video_with_files(db: Session, video: Video, staging: Path, final_folder: Path) -> None:
    moved = False
    try:
        if final_folder.exists():
            raise FileExistsError(f"Le dossier média existe déjà: {final_folder}")
        move_directory(staging, final_folder)
        moved = True
        db.add(video)
        db.commit()
    except Exception:
        db.rollback()
        if moved:
            remove_directory(final_folder)
        else:
            remove_directory(staging)
        raise


def merge_staged_files(db: Session, video: Video, staging: Path, final_folder: Path) -> None:
    moved_files: list[Path] = []
    replaced_files: list[tuple[Path, Path]] = []
    backup_folder = unique_sibling_path(final_folder, "replace")
    try:
        final_folder.mkdir(parents=True, exist_ok=True)
        for staged_file in staging.iterdir():
            if not staged_file.is_file():
                continue
            target = final_folder / staged_file.name
            if target.exists():
                backup_folder.mkdir(parents=True, exist_ok=True)
                backup = backup_folder / staged_file.name
                target.replace(backup)
                replaced_files.append((target, backup))
            staged_file.replace(target)
            moved_files.append(target)
        remove_directory(staging)
        db.add(video)
        db.commit()
        remove_directory(backup_folder)
    except Exception:
        db.rollback()
        for target in reversed(moved_files):
            if target.exists():
                target.unlink()
        for target, backup in reversed(replaced_files):
            if backup.exists():
                backup.replace(target)
        remove_directory(staging)
        remove_directory(backup_folder)
        raise


def retry_transcript_download(
    db: Session, video: Video, languages: list[str] | None = None
) -> Video:
    # No explicit language: one attempt, on the track `choose_subtitle_track` picks.
    attempts: list[list[str] | None] = (
        [[language] for language in languages] if languages else [None]
    )
    final_folder = Path(video.folder_path)
    staging = staged_folder(final_folder)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        subtitle_path = None
        for attempt in attempts:
            try:
                download_subtitles(video.url, staging, languages=attempt)
            except Exception:
                continue
            files = discover_downloaded_files(staging)
            if files["subtitle_path"]:
                subtitle_path = files["subtitle_path"]
                break
        if subtitle_path is None:
            raise ValueError("Aucun sous-titre disponible pour cette vidéo.")
        transcript_path, transcript_status = write_transcript(staging, subtitle_path)
        for stale in final_folder.glob("*"):
            if stale.is_file() and stale.suffix.lower() in SUBTITLE_EXTENSIONS:
                stale.unlink()
        video.subtitle_path = str(final_path(subtitle_path, staging, final_folder))
        video.transcript_path = (
            str(final_path(transcript_path, staging, final_folder)) if transcript_path else None
        )
        video.transcript_status = transcript_status
        merge_staged_files(db, video, staging, final_folder)
        db.refresh(video)
        return video
    except Exception:
        remove_directory(staging)
        raise


def media_type_for_paths(
    video_path: str | None, audio_path: str | None, metadata_path: str | None
) -> str:
    if video_path:
        return "video"
    if audio_path:
        return "audio"
    if metadata_path:
        return "metadata"
    return "metadata"


def canonical_video_url(video_url: str, yt_video_id: str, source_section: str = "videos") -> str:
    if source_section in {"short", "shorts"}:
        return f"https://www.youtube.com/shorts/{yt_video_id}"
    return video_url


def video_source_section(*urls: str | None) -> str:
    return "shorts" if any(url and "/shorts/" in url for url in urls) else "videos"


def channel_values_from_info(
    info: dict, fallback_url: str | None = None
) -> tuple[str | None, str | None, str | None]:
    yt_channel_id = info.get("channel_id") or info.get("uploader_id")
    url = info.get("channel_url") or info.get("uploader_url")
    name = display_channel_name_from_info(info, url, yt_channel_id)
    if not url and yt_channel_id:
        url = f"https://www.youtube.com/channel/{yt_channel_id}"
    if not url and name:
        url = f"raton:channel:{quote(str(name), safe='')}"
    if not name and fallback_url:
        name = urlparse(fallback_url).netloc or fallback_url
    return (
        str(name) if name else None,
        str(url) if url else None,
        str(yt_channel_id) if yt_channel_id else None,
    )


def looks_like_youtube_channel_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith("UC") and len(value) >= 12


def channel_handle_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path_segments = [segment for segment in urlparse(str(url)).path.split("/") if segment]
    handle = next((segment for segment in path_segments if segment.startswith("@")), None)
    return unquote(handle[1:]) if handle else None


def display_channel_name_from_info(
    info: dict, url: str | None, yt_channel_id: object = None
) -> str | None:
    id_values = {
        str(value)
        for value in (
            yt_channel_id,
            info.get("channel_id"),
            info.get("uploader_id"),
            info.get("id"),
        )
        if value
    }
    for key in ("channel", "uploader", "creator", "channel_title", "uploader_name"):
        value = info.get(key)
        if not value:
            continue
        text = str(value)
        if text not in id_values and not looks_like_youtube_channel_id(text):
            return text
    return channel_handle_from_url(url)


def get_or_create_channel_from_info(
    db: Session,
    info: dict,
    fallback_url: str | None = None,
    rating: int = 0,
) -> Channel | None:
    name, url, yt_channel_id = channel_values_from_info(info, fallback_url)
    if not name or not url:
        return None
    channel = None
    if yt_channel_id:
        channel = db.scalar(select(Channel).where(Channel.yt_channel_id == yt_channel_id))
    if channel is None:
        channel = db.scalar(select(Channel).where(Channel.url == url))
    if channel:
        if not channel.yt_channel_id and yt_channel_id:
            channel.yt_channel_id = yt_channel_id
        if channel.name != name:
            channel.name = name
        return channel
    channel = Channel(url=url, name=name, yt_channel_id=yt_channel_id, rating=rating)
    db.add(channel)
    db.flush()
    return channel


def ensure_video_channel(db: Session, video: Video) -> Channel | None:
    if video.channel:
        if video.channel.category_labels and not video.category_labels:
            video.category_labels = video.channel.category_labels
            db.add(video)
            db.commit()
            db.refresh(video)
        return video.channel
    metadata = {}
    if video.metadata_path:
        path = local_media_path(video.metadata_path)
        if path.is_file():
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}
    channel = get_or_create_channel_from_info(db, metadata, video.url)
    if channel:
        video.channel = channel
        if channel.category_labels and not video.category_labels:
            video.category_labels = channel.category_labels
        db.add(video)
        db.commit()
        db.refresh(video)
    return channel


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
) -> int:
    """Import the metadata of the channel's new videos and return how many were imported.

    Listing and importing are two phases so `max_imports` can leave a backlog for the next scan:
    the entries to import are collected first, then imported oldest first. The leftovers are then
    the newest ones, still ahead of the first known video, so the next scan finds them again.
    Importing newest first would strand them behind a known video.

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
            if video_already_downloaded(db, yt_video_id):
                if is_shorts:
                    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
                    if existing and "/shorts/" not in existing.url:
                        existing.url = canonical_video_url(existing.url, yt_video_id, "shorts")
                        db.add(existing)
                        db.commit()
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


def extract_audio_from_downloaded_video(db: Session, video: Video) -> bool:
    """Add the audio of a video already on disk by copying its track; False leaves the video untouched.

    False means "use yt-dlp": no local video, an audio already there, a track of lower quality than a
    dedicated download, or an ffmpeg failure.
    """
    if video.audio_path:
        return False
    source = extractable_video_file(video)
    if source is None:
        return False
    final_folder = Path(video.folder_path)
    staging = staged_folder(final_folder)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        target = staging / f"{source.stem}.m4a"
        if not copy_audio_track(source, target):
            remove_directory(staging)
            return False
        video.audio_path = str(final_folder / target.name)
        # A new cache entry: restart the 7-day countdown, as a re-download does.
        video.watched_at = None
        video.media_type = media_type_for_paths(
            video.video_path, video.audio_path, video.metadata_path
        )
        merge_staged_files(db, video, staging, final_folder)
        video.file_size_bytes = directory_size(final_folder)
        db.commit()
    except Exception:
        db.rollback()
        remove_directory(staging)
        raise
    log_job(
        db, "downloaded", f"Audio extracted from the video file: {video.title}", video_id=video.id
    )
    return True


def download_manual_media(
    db: Session,
    video_url: str,
    media_type: str,
    download_transcript: bool,
    subtitle_languages: list[str] | None = None,
    subtitle_source: str = "auto",
    is_new: bool = False,
    video_quality: str = "1080",
) -> Video:
    if media_type not in {"video", "audio"}:
        raise ValueError("Le format doit être vidéo ou audio.")
    ensure_public_http_url(video_url)

    if media_type == "audio":
        # Looked up by URL, not by yt id, so the common case (audio of a downloaded video) skips the network.
        known = db.scalar(select(Video).where(Video.url == video_url))
        if known is not None and extract_audio_from_downloaded_video(db, known):
            return known

    preview = extract_video_info(video_url)
    yt_video_id = str(preview.get("id") or "")
    if not yt_video_id:
        raise ValueError("Impossible d'identifier cette vidéo.")
    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    if existing and media_type == "video" and existing.video_path:
        raise ValueError("La vidéo a déjà été téléchargée.")
    if existing and media_type == "audio" and existing.audio_path:
        raise ValueError("L'audio a déjà été téléchargé.")
    source_section = video_source_section(
        video_url, existing.url if existing else None, preview.get("webpage_url")
    )

    title = preview.get("title") or yt_video_id
    channel = (
        existing.channel
        if existing and existing.channel
        else get_or_create_channel_from_info(db, preview, video_url)
    )
    uploader = (
        channel.name
        if channel
        else preview.get("channel") or preview.get("uploader") or "Chaîne inconnue"
    )
    published_at = parse_yt_date(preview.get("upload_date") or preview.get("timestamp"))
    folder = (
        Path(existing.folder_path)
        if existing
        else build_video_folder(get_media_root(db), uploader, title, published_at)
    )
    staging = staged_folder(folder)

    try:
        if video_quality == "1080":
            info = download_media(video_url, staging, media_type)
        else:
            info = download_media(video_url, staging, media_type, video_quality)
        if download_transcript:
            try:
                download_subtitles(
                    video_url,
                    staging,
                    languages=subtitle_languages,
                    include_auto=subtitle_source in {"auto", "both"},
                    include_manual=subtitle_source in {"manual", "both"},
                    info=info,
                )
            except Exception as exc:
                log_job(db, "warning", f"Media downloaded without transcript: {exc}")
        files = discover_downloaded_files(staging)
        metadata_path = write_metadata(staging, info)
        transcript_path, transcript_status = (
            write_transcript(staging, files["subtitle_path"])
            if download_transcript
            else (None, TranscriptStatus.missing)
        )
        if existing:
            existing.title = info.get("title") or title
            existing.url = canonical_video_url(
                info.get("webpage_url") or video_url, yt_video_id, source_section
            )
            if not existing.channel:
                existing.channel = get_or_create_channel_from_info(db, info, video_url) or channel
            if (
                existing.channel
                and existing.channel.category_labels
                and not existing.category_labels
            ):
                existing.category_labels = existing.channel.category_labels
            existing.download_source = "manual"
            existing.published_at = parse_yt_date(info.get("upload_date")) or published_at
            existing.downloaded_at = datetime.now(UTC)
            if files["video_path"] or files["audio_path"]:
                # A re-download is a new cache entry: restart the 7-day countdown,
                # or the purge would delete the fresh file on its next run.
                existing.watched_at = None
            if files["video_path"]:
                existing.video_path = str(final_path(files["video_path"], staging, folder))
            if files["audio_path"]:
                existing.audio_path = str(final_path(files["audio_path"], staging, folder))
            if files["thumbnail_path"]:
                existing.thumbnail_path = str(final_path(files["thumbnail_path"], staging, folder))
            existing.metadata_path = str(final_path(metadata_path, staging, folder))
            existing.view_count = parse_view_count(info.get("view_count"))
            existing.duration_seconds = parse_duration_seconds(info.get("duration"))
            if files["subtitle_path"]:
                existing.subtitle_path = str(final_path(files["subtitle_path"], staging, folder))
            if transcript_path:
                existing.transcript_path = str(final_path(transcript_path, staging, folder))
                existing.transcript_status = transcript_status
            elif not existing.transcript_path:
                existing.transcript_status = transcript_status
            existing.media_type = media_type_for_paths(
                existing.video_path, existing.audio_path, existing.metadata_path
            )
            merge_staged_files(db, existing, staging, folder)
            existing.file_size_bytes = directory_size(folder)
            db.commit()
            video = existing
            ensure_video_thumbnails(video)
        else:
            video_path = (
                str(final_path(files["video_path"], staging, folder))
                if files["video_path"]
                else None
            )
            audio_path = (
                str(final_path(files["audio_path"], staging, folder))
                if files["audio_path"]
                else None
            )
            metadata_final_path = str(final_path(metadata_path, staging, folder))
            subtitle_final_path = (
                str(final_path(files["subtitle_path"], staging, folder))
                if files["subtitle_path"]
                else None
            )
            video = Video(
                channel=channel or get_or_create_channel_from_info(db, info, video_url),
                yt_video_id=yt_video_id,
                title=info.get("title") or title,
                url=canonical_video_url(
                    info.get("webpage_url") or video_url, yt_video_id, source_section
                ),
                media_type=media_type_for_paths(video_path, audio_path, metadata_final_path),
                download_source="manual",
                imported_via_form=True,
                category_labels=channel.category_labels if channel else None,
                published_at=parse_yt_date(info.get("upload_date")) or published_at,
                downloaded_at=datetime.now(UTC),
                folder_path=str(folder),
                video_path=video_path,
                audio_path=audio_path,
                thumbnail_path=str(final_path(files["thumbnail_path"], staging, folder))
                if files["thumbnail_path"]
                else None,
                metadata_path=metadata_final_path,
                view_count=parse_view_count(info.get("view_count")),
                duration_seconds=parse_duration_seconds(info.get("duration")),
                subtitle_path=subtitle_final_path,
                transcript_path=str(final_path(transcript_path, staging, folder))
                if transcript_path
                else None,
                transcript_status=transcript_status,
                file_size_bytes=directory_size(staging),
            )
            commit_video_with_files(db, video, staging, folder)
        db.refresh(video)
        ensure_video_thumbnails(video)
        log_job(db, "downloaded", f"Downloaded {video.title}", video_id=video.id)
        try:
            categories = get_sponsor_segment_categories(db)
            segments = fetch_sponsorblock_segments(video.yt_video_id, categories)
            replace_video_sponsor_segments(db, video.id, "sponsorblock", segments)
        except Exception:
            # SponsorBlock is best-effort here; the manual "Rechercher" button covers
            # retries. Roll back so a failure inside replace_video_sponsor_segments
            # (e.g. a DB error mid-commit) doesn't leave the session poisoned for the
            # caller's own subsequent commits (run_manual_download_job's job-status update).
            db.rollback()
        return video
    except Exception:
        db.rollback()
        remove_directory(staging)
        raise


def import_video_metadata(
    db: Session,
    video_url: str,
    channel_id: int | None = None,
    preview: dict | None = None,
    download_source: str = "manual",
    source_section: str = "videos",
    subtitle_languages: list[str] | None = None,
    subtitle_source: str = "auto",
    is_new: bool = False,
) -> Video:
    ensure_public_http_url(video_url)

    try:
        extracted = extract_video_info(video_url)
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise RateLimitedError(f"YouTube limite les requêtes (HTTP 429): {exc}") from exc
        raise
    info = {**preview, **extracted} if preview else extracted
    yt_video_id = str(info.get("id") or "")
    if not yt_video_id:
        raise ValueError("Impossible d'identifier cette vidéo.")
    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    if existing:
        if source_section in {"short", "shorts"} and "/shorts/" not in existing.url:
            existing.url = canonical_video_url(existing.url, yt_video_id, source_section)
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    channel = (
        db.get(Channel, channel_id)
        if channel_id
        else get_or_create_channel_from_info(db, info, video_url)
    )
    title = info.get("title") or yt_video_id
    uploader = (
        channel.name
        if channel
        else info.get("channel") or info.get("uploader") or "Métadonnées YouTube"
    )
    published_at = parse_yt_date(info.get("upload_date") or info.get("timestamp"))
    folder = build_video_folder(get_media_root(db), uploader, title, published_at)
    staging = staged_folder(folder)
    # No row for this yt_video_id but the folder is still on disk (row deleted, files kept): re-link
    # it in place instead of staging a copy, so the media files in it are kept, not refused.
    adopting = folder.is_dir()
    work = folder if adopting else staging

    try:
        if not adopting:
            staging.mkdir(parents=True, exist_ok=True)
        if not (adopting and discover_downloaded_files(work)["subtitle_path"]):
            try:
                download_subtitles(
                    video_url,
                    work,
                    languages=subtitle_languages,
                    include_auto=subtitle_source in {"auto", "both"},
                    include_manual=subtitle_source in {"manual", "both"},
                    info=extracted,
                )
            except Exception as exc:
                # Not a reason to stop the scan: only translated tracks answer 429 and those are
                # no longer requested, so a failure here costs this video its transcript at most.
                log_job(
                    db,
                    "warning",
                    f"Metadata imported without transcript: {exc}",
                    channel_id=channel_id,
                )
        if not (adopting and discover_downloaded_files(work)["thumbnail_path"]):
            try:
                download_thumbnail(video_url, work, info=extracted)
            except Exception as exc:
                if is_rate_limit_error(exc):
                    raise RateLimitedError(
                        f"YouTube limite les requêtes (HTTP 429): {exc}"
                    ) from exc
                log_job(
                    db,
                    "warning",
                    f"Metadata imported without thumbnail: {exc}",
                    channel_id=channel_id,
                )
        files = discover_downloaded_files(work)
        metadata_path = write_metadata(work, info)
        transcript_path, transcript_status = write_transcript(work, files["subtitle_path"])
        video_path = final_path(files["video_path"], work, folder)
        audio_path = final_path(files["audio_path"], work, folder)
        video = Video(
            channel=channel,
            yt_video_id=yt_video_id,
            title=info.get("title") or title,
            url=canonical_video_url(
                info.get("webpage_url") or video_url, yt_video_id, source_section
            ),
            media_type=media_type_for_paths(
                str(video_path) if video_path else None,
                str(audio_path) if audio_path else None,
                str(metadata_path),
            ),
            download_source=download_source,
            imported_via_form=download_source == "manual",
            is_new=is_new,
            category_labels=channel.category_labels if channel else None,
            published_at=parse_yt_date(info.get("upload_date")) or published_at,
            downloaded_at=datetime.now(UTC),
            folder_path=str(folder),
            video_path=str(video_path) if video_path else None,
            audio_path=str(audio_path) if audio_path else None,
            thumbnail_path=str(final_path(files["thumbnail_path"], work, folder))
            if files["thumbnail_path"]
            else None,
            metadata_path=str(final_path(metadata_path, work, folder)),
            view_count=parse_view_count(info.get("view_count")),
            duration_seconds=parse_duration_seconds(info.get("duration")),
            subtitle_path=str(final_path(files["subtitle_path"], work, folder))
            if files["subtitle_path"]
            else None,
            transcript_path=str(final_path(transcript_path, work, folder))
            if transcript_path
            else None,
            transcript_status=transcript_status,
            file_size_bytes=directory_size(work),
        )
        if adopting:
            db.add(video)
            db.commit()
        else:
            commit_video_with_files(db, video, staging, folder)
        db.refresh(video)
        ensure_video_thumbnails(video)
        if download_source == "manual":
            log_job(
                db,
                "metadata",
                f"Imported metadata for {video.title}",
                channel_id=channel_id,
                video_id=video.id,
            )
        return video
    except Exception:
        db.rollback()
        remove_directory(staging)
        raise


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
                    pause(PAUSE_BETWEEN_CHANNELS if previous_imported else PAUSE_AFTER_LISTING_ONLY)
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
