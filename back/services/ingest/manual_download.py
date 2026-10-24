"""Manual download of one video's media (video or audio), asked from the download form."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.video import TranscriptStatus, Video
from back.services.common.files import directory_size, remove_directory
from back.services.common.job_log import log_job
from back.services.common.settings import get_media_root
from back.services.ingest.identity import (
    canonical_video_url,
    get_or_create_channel_from_info,
    video_source_section,
)
from back.services.ingest.staging import (
    commit_video_with_files,
    extract_audio_from_downloaded_video,
    final_path_str,
    merge_staged_files,
    staged_folder,
)
from back.services.media.media_storage import media_type_for_paths
from back.services.media.thumbnails import ensure_video_thumbnails
from back.services.youtube.downloads import (
    build_video_folder,
    discover_downloaded_files,
    download_media,
    download_subtitles,
    write_metadata,
    write_transcript,
)
from back.services.youtube.sponsor_segments import fetch_sponsor_segments
from back.services.youtube.url_guard import ensure_public_http_url
from back.services.youtube.view_counts import parse_duration_seconds, parse_view_count
from back.services.youtube.yt import extract_video_info, parse_yt_date


@dataclass
class _Download:
    """What landed in the staging folder, with the paths it will have in the final folder."""

    info: dict[str, Any]
    staging: Path
    folder: Path
    files: dict[str, Path | None]
    metadata_path: Path
    transcript_path: Path | None
    transcript_status: TranscriptStatus

    def final(self, path: Path | None) -> str | None:
        return final_path_str(path, self.staging, self.folder)


def download_manual_media(
    db: Session,
    video_url: str,
    media_type: str,
    download_transcript: bool,
    subtitle_languages: list[str] | None = None,
    subtitle_source: str = "auto",
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
        download = _download_to_staging(
            db,
            video_url,
            media_type,
            staging,
            folder,
            download_transcript=download_transcript,
            subtitle_languages=subtitle_languages,
            subtitle_source=subtitle_source,
            video_quality=video_quality,
        )
        url = canonical_video_url(
            download.info.get("webpage_url") or video_url, yt_video_id, source_section
        )
        published_at = parse_yt_date(download.info.get("upload_date")) or published_at
        if existing:
            video = _add_to_existing_fiche(
                db, existing, download, video_url, url, title, channel, published_at
            )
        else:
            video = _new_fiche(
                db, download, video_url, url, yt_video_id, title, channel, published_at
            )
            commit_video_with_files(db, video, staging, folder)
        db.refresh(video)
        ensure_video_thumbnails(video)
        log_job(db, "downloaded", f"Downloaded {video.title}", video_id=video.id)
        try:
            fetch_sponsor_segments(db, video)
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


def _download_to_staging(
    db: Session,
    video_url: str,
    media_type: str,
    staging: Path,
    folder: Path,
    *,
    download_transcript: bool,
    subtitle_languages: list[str] | None,
    subtitle_source: str,
    video_quality: str,
) -> _Download:
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
    return _Download(
        info, staging, folder, files, metadata_path, transcript_path, transcript_status
    )


def _add_to_existing_fiche(
    db: Session,
    video: Video,
    download: _Download,
    video_url: str,
    url: str,
    title: str,
    channel: Channel | None,
    published_at: datetime | None,
) -> Video:
    """Merge the new format into the fiche's folder, keeping the format it already has."""
    info, files = download.info, download.files
    video.title = info.get("title") or title
    video.url = url
    if not video.channel:
        video.channel = get_or_create_channel_from_info(db, info, video_url) or channel
    if video.channel and video.channel.category_labels and not video.category_labels:
        video.category_labels = video.channel.category_labels
    video.download_source = "manual"
    video.published_at = published_at
    video.downloaded_at = datetime.now(UTC)
    if files["video_path"] or files["audio_path"]:
        # A re-download is a new cache entry: restart the 7-day countdown,
        # or the purge would delete the fresh file on its next run.
        video.watched_at = None
    if files["video_path"]:
        video.video_path = download.final(files["video_path"])
    if files["audio_path"]:
        video.audio_path = download.final(files["audio_path"])
    if files["thumbnail_path"]:
        video.thumbnail_path = download.final(files["thumbnail_path"])
    video.metadata_path = download.final(download.metadata_path)
    video.view_count = parse_view_count(info.get("view_count"))
    video.duration_seconds = parse_duration_seconds(info.get("duration"))
    if files["subtitle_path"]:
        video.subtitle_path = download.final(files["subtitle_path"])
    if download.transcript_path:
        video.transcript_path = download.final(download.transcript_path)
        video.transcript_status = download.transcript_status
    elif not video.transcript_path:
        video.transcript_status = download.transcript_status
    video.media_type = media_type_for_paths(video.video_path, video.audio_path, video.metadata_path)
    merge_staged_files(db, video, download.staging, download.folder)
    video.file_size_bytes = directory_size(download.folder)
    db.commit()
    return video


def _new_fiche(
    db: Session,
    download: _Download,
    video_url: str,
    url: str,
    yt_video_id: str,
    title: str,
    channel: Channel | None,
    published_at: datetime | None,
) -> Video:
    """The unsaved fiche of a video the library did not have."""
    info, files = download.info, download.files
    video_path = download.final(files["video_path"])
    audio_path = download.final(files["audio_path"])
    metadata_path = download.final(download.metadata_path)
    return Video(
        channel=channel or get_or_create_channel_from_info(db, info, video_url),
        yt_video_id=yt_video_id,
        title=info.get("title") or title,
        url=url,
        media_type=media_type_for_paths(video_path, audio_path, metadata_path),
        download_source="manual",
        imported_via_form=True,
        category_labels=channel.category_labels if channel else None,
        published_at=published_at,
        downloaded_at=datetime.now(UTC),
        folder_path=str(download.folder),
        video_path=video_path,
        audio_path=audio_path,
        thumbnail_path=download.final(files["thumbnail_path"]),
        metadata_path=metadata_path,
        view_count=parse_view_count(info.get("view_count")),
        duration_seconds=parse_duration_seconds(info.get("duration")),
        subtitle_path=download.final(files["subtitle_path"]),
        transcript_path=download.final(download.transcript_path),
        transcript_status=download.transcript_status,
        file_size_bytes=directory_size(download.staging),
    )
