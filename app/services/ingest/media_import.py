"""Download of one video's media, metadata or transcript, outside the scheduled scan
(manual download, metadata import, transcript retry); the scan calls `import_video_metadata` too.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import TranscriptStatus, Video
from app.services.common.files import (
    directory_size,
    remove_directory,
)
from app.services.common.job_log import log_job
from app.services.common.settings import get_media_root
from app.services.ingest.identity import (
    canonical_video_url,
    get_or_create_channel_from_info,
    video_source_section,
)
from app.services.ingest.staging import (
    commit_video_with_files,
    extract_audio_from_downloaded_video,
    final_path,
    merge_staged_files,
    staged_folder,
)
from app.services.ingest.throttle import RateLimitedError
from app.services.media.media_storage import media_type_for_paths
from app.services.media.thumbnails import ensure_video_thumbnails
from app.services.youtube.downloads import (
    SUBTITLE_EXTENSIONS,
    build_video_folder,
    discover_downloaded_files,
    download_media,
    download_subtitles,
    download_thumbnail,
    write_metadata,
    write_transcript,
)
from app.services.youtube.sponsor_segments import fetch_sponsor_segments
from app.services.youtube.url_guard import ensure_public_http_url
from app.services.youtube.view_counts import parse_duration_seconds, parse_view_count
from app.services.youtube.yt import extract_video_info, is_rate_limit_error, parse_yt_date


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
