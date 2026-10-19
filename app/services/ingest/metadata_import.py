"""Metadata import of one video: its fiche, thumbnail and transcript, without the media file.

Called by the scan, the playlist imports, the channel exploration and the import form.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import Video
from app.services.common.files import directory_size, remove_directory
from app.services.common.job_log import log_job
from app.services.common.settings import get_media_root
from app.services.ingest.identity import canonical_video_url, get_or_create_channel_from_info
from app.services.ingest.staging import (
    commit_video_with_files,
    final_path,
    final_path_str,
    staged_folder,
)
from app.services.ingest.throttle import RateLimitedError
from app.services.media.media_storage import media_type_for_paths
from app.services.media.thumbnails import ensure_video_thumbnails
from app.services.youtube.downloads import (
    build_video_folder,
    discover_downloaded_files,
    download_subtitles,
    download_thumbnail,
    write_metadata,
    write_transcript,
)
from app.services.youtube.url_guard import ensure_public_http_url
from app.services.youtube.view_counts import parse_duration_seconds, parse_view_count
from app.services.youtube.yt import extract_video_info, is_rate_limit_error, parse_yt_date


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
    """The fiche of `video_url`, created with its side files when the library lacks it."""
    ensure_public_http_url(video_url)
    extracted = _extract_info(video_url)
    info = {**preview, **extracted} if preview else extracted
    yt_video_id = str(info.get("id") or "")
    if not yt_video_id:
        raise ValueError("Impossible d'identifier cette vidéo.")
    existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    if existing:
        return _relink_as_short(db, existing, yt_video_id, source_section)

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
        _download_side_files(
            db,
            video_url,
            work,
            extracted,
            adopting,
            channel_id,
            subtitle_languages,
            subtitle_source,
        )
        video = _new_fiche(
            info,
            video_url,
            yt_video_id,
            title,
            channel,
            published_at,
            work,
            folder,
            download_source=download_source,
            source_section=source_section,
            is_new=is_new,
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


def _extract_info(video_url: str) -> dict[str, Any]:
    try:
        return extract_video_info(video_url)
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise RateLimitedError(f"YouTube limite les requêtes (HTTP 429): {exc}") from exc
        raise


def _relink_as_short(db: Session, video: Video, yt_video_id: str, source_section: str) -> Video:
    """A known fiche met again in a channel's shorts tab gets its `/shorts/` URL."""
    if source_section in {"short", "shorts"} and "/shorts/" not in video.url:
        video.url = canonical_video_url(video.url, yt_video_id, source_section)
        db.add(video)
        db.commit()
        db.refresh(video)
    return video


def _download_side_files(
    db: Session,
    video_url: str,
    work: Path,
    extracted: dict[str, Any],
    adopting: bool,
    channel_id: int | None,
    subtitle_languages: list[str] | None,
    subtitle_source: str,
) -> None:
    """Subtitles and thumbnail into `work`, skipping those an adopted folder already holds."""
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
                raise RateLimitedError(f"YouTube limite les requêtes (HTTP 429): {exc}") from exc
            log_job(
                db,
                "warning",
                f"Metadata imported without thumbnail: {exc}",
                channel_id=channel_id,
            )


def _new_fiche(
    info: dict[str, Any],
    video_url: str,
    yt_video_id: str,
    title: str,
    channel: Channel | None,
    published_at: datetime | None,
    work: Path,
    folder: Path,
    *,
    download_source: str,
    source_section: str,
    is_new: bool,
) -> Video:
    """The unsaved fiche, its paths pointing where `work`'s files end up in `folder`."""
    files = discover_downloaded_files(work)
    metadata_path = write_metadata(work, info)
    transcript_path, transcript_status = write_transcript(work, files["subtitle_path"])
    video_path = final_path_str(files["video_path"], work, folder)
    audio_path = final_path_str(files["audio_path"], work, folder)
    return Video(
        channel=channel,
        yt_video_id=yt_video_id,
        title=info.get("title") or title,
        url=canonical_video_url(info.get("webpage_url") or video_url, yt_video_id, source_section),
        media_type=media_type_for_paths(video_path, audio_path, str(metadata_path)),
        download_source=download_source,
        imported_via_form=download_source == "manual",
        is_new=is_new,
        category_labels=channel.category_labels if channel else None,
        published_at=parse_yt_date(info.get("upload_date")) or published_at,
        downloaded_at=datetime.now(UTC),
        folder_path=str(folder),
        video_path=video_path,
        audio_path=audio_path,
        thumbnail_path=final_path_str(files["thumbnail_path"], work, folder),
        metadata_path=str(final_path(metadata_path, work, folder)),
        view_count=parse_view_count(info.get("view_count")),
        duration_seconds=parse_duration_seconds(info.get("duration")),
        subtitle_path=final_path_str(files["subtitle_path"], work, folder),
        transcript_path=final_path_str(transcript_path, work, folder),
        transcript_status=transcript_status,
        file_size_bytes=directory_size(work),
    )
