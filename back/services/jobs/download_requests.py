"""The request side of download, import and exploration jobs: what a route answers with.

`queue_*` validate and create the queued `DownloadJob`; the route then hands the matching runner
of `downloads` to its background tasks. `job_status` is what a client polls afterwards,
`cancel_job` stops an exploration. Shared by the HTML routes and `/api`.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.channels.manage import bell_section_label
from back.services.common.categories import serialized_category_labels
from back.services.common.job_log import JOB_DONE_STATUSES, log_job
from back.services.common.settings import add_video_category_labels
from back.services.ingest.channel_exploration import (
    cancel_channel_exploration,
    channel_exploration_videos,
)
from back.services.jobs import downloads
from back.services.playlists.editing import videos_missing_media
from back.services.videos.download_options import (
    normalize_download_media_types,
    normalize_subtitle_language,
    normalize_subtitle_source,
    normalize_video_quality,
)

# Formats a fiche can download on its own (`queue_media_download`).
FICHE_MEDIA_TYPES = ("audio", "video")


class InvalidMediaFormatError(ValueError):
    pass


class ManualDownloadRefusedError(ValueError):
    pass


class NotAYouTubeLinkError(ValueError):
    def __init__(self) -> None:
        super().__init__("Ce n'est pas un lien YouTube.")


# Hosts a shared link may come from (Safari, the YouTube app, YouTube Music).
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


@dataclass(frozen=True)
class ManualDownload:
    """A download of the import page, validated; `run_args` are `run_manual_download_job`'s."""

    url: str
    media_types: list[str]
    download_transcript: bool
    category_labels: str | None
    subtitle_language: str | None
    subtitle_source: str
    video_quality: str

    def run_args(self) -> tuple:
        return (
            self.url,
            self.media_types,
            self.download_transcript,
            self.category_labels,
            self.subtitle_language,
            self.subtitle_source,
            self.video_quality,
        )


class JobNotFoundError(ValueError):
    def __init__(self) -> None:
        super().__init__("Job introuvable")


def queue_manual_download(
    db: Session,
    url: str,
    media_types: list[str],
    download_transcript: bool,
    video_quality: str = "1080",
    categories: list[str] = (),
    subtitle_language: str = "",
    subtitle_source: str = "both",
) -> tuple[DownloadJob, ManualDownload]:
    """The queued job of a download from the import page. A refused option is logged in the
    journal and raised as `ManualDownloadRefusedError` with its message."""
    try:
        download = ManualDownload(
            url=url,
            media_types=normalize_download_media_types(media_types),
            download_transcript=download_transcript,
            category_labels=serialized_category_labels(list(categories)),
            # Empty: no language imposed, `choose_subtitle_track` picks the original track.
            subtitle_language=normalize_subtitle_language(subtitle_language),
            subtitle_source=normalize_subtitle_source(subtitle_source),
            video_quality=normalize_video_quality(video_quality),
        )
        add_video_category_labels(db, list(categories))
        job = log_job(db, "queued", "Téléchargement en file d'attente.")
    except Exception as exc:
        db.rollback()
        log_job(db, "failed", f"Manual download failed: {exc}")
        raise ManualDownloadRefusedError(str(exc)) from exc
    return job, download


def import_shared_video(db: Session, url: str) -> DownloadJob:
    """A link shared from the iOS share sheet, imported now (metadata and transcript, no media),
    so the Shortcut can open the fiche: the caller checks `status` and `video_id`."""
    url = url.strip()
    if urlparse(url).hostname not in YOUTUBE_HOSTS:
        raise NotAYouTubeLinkError()
    job = log_job(db, "queued", "Import depuis le partage iOS en file d'attente.")
    # Through its module: tests replace the runner there.
    downloads.run_manual_download_job(job.id, url, ["metadata"], True)
    db.refresh(job)
    return job


def queue_media_download(
    db: Session, video: Video, media_type: str, video_quality: str = "1080"
) -> DownloadJob:
    """The queued job of a missing format of a fiche; run it with `run_media_download_job`."""
    if media_type not in FICHE_MEDIA_TYPES:
        raise InvalidMediaFormatError("Le format doit être vidéo ou audio.")
    try:
        normalize_video_quality(video_quality)
    except ValueError as exc:
        raise InvalidMediaFormatError(str(exc)) from exc
    return log_job(db, "queued", "Téléchargement en file d'attente.", video_id=video.id)


def queue_playlist_downloads(
    db: Session, playlist, media_type: str
) -> list[tuple[Video, DownloadJob]]:
    """One `queue_media_download` per video of the playlist without that format yet."""
    if media_type not in FICHE_MEDIA_TYPES:
        raise InvalidMediaFormatError("Le format doit être vidéo ou audio.")
    return [
        (video, queue_media_download(db, video, media_type))
        for video in videos_missing_media(playlist, media_type)
    ]


def queue_transcript_retry(db: Session, video: Video) -> DownloadJob:
    """The queued job of a new transcript attempt; run it with `run_transcript_retry_job`."""
    return log_job(db, "queued", "Récupération du transcript en file d'attente.", video_id=video.id)


def queue_channel_metadata_import(db: Session, channel: Channel, section: str) -> DownloadJob:
    """The queued import of a page of a channel's metadata; run `run_channel_metadata_import_job`."""
    return log_job(
        db,
        "queued",
        f"Import des métadonnées {bell_section_label(section)} de {channel.name} en file d'attente.",
        channel_id=channel.id,
    )


def queue_channel_catalog_sync(db: Session, channel: Channel, section: str) -> DownloadJob:
    """The queued sync of the catalogue of a cloche just turned on; run its first page with
    `run_channel_metadata_import_job`."""
    return log_job(
        db,
        "queued",
        f"Recherche automatique des nouveautés ({bell_section_label(section)}) de {channel.name}"
        " en file d'attente.",
        channel_id=channel.id,
    )


def cancel_job(db: Session, job_id: int) -> dict:
    """Stop a channel exploration (it stops before its next video); returns the job's status."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise JobNotFoundError()
    cancel_channel_exploration(db, job)
    return job_status(db, job_id)


def job_status(db: Session, job_id: int) -> dict:
    """What a client polls while a job runs; a channel exploration adds the fiches it imported."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise JobNotFoundError()
    payload = {
        "id": job.id,
        "status": job.status,
        "message": job.message,
        "video_id": job.video_id,
        "done": job.status in JOB_DONE_STATUSES,
    }
    imported = channel_exploration_videos(db, job)
    if imported is not None:
        payload["videos"] = imported
    return payload
