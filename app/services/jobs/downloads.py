"""Background jobs of a download: manual download, transcript retry, metadata import of a channel.

Each `run_*` opens its own session and updates the `DownloadJob` that `download_requests`
queued for it.
"""

import logging

from sqlalchemy import select

from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.ingest.manual_download import download_manual_media
from app.services.ingest.metadata_import import import_video_metadata
from app.services.ingest.scanner import scan_channel_section
from app.services.ingest.transcript_retry import retry_transcript_download

logger = logging.getLogger(__name__)


CHANNEL_VIDEO_PAGE_SIZE = 25


def run_media_download_job(
    job_id: int, video_url: str, media_type: str, video_quality: str = "1080"
) -> None:
    # The fiche's metadata is refreshed along the way; its transcript is left alone.
    run_manual_download_job(
        job_id, video_url, [media_type, "metadata"], False, video_quality=video_quality
    )


@logged_job("manual_download")
def run_manual_download_job(
    job_id: int,
    video_url: str,
    media_types: list[str],
    download_transcript: bool,
    category_labels: str | None = None,
    subtitle_language: str | None = None,
    subtitle_source: str = "both",
    video_quality: str = "1080",
) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Téléchargement en cours..."
        db.commit()

        video = None
        subtitle_languages = [subtitle_language] if subtitle_language else None
        subtitle_source = subtitle_source if download_transcript else "none"
        for media_type in media_types:
            if media_type == "metadata":
                if video is None:
                    video = import_video_metadata(
                        db,
                        video_url,
                        subtitle_languages=subtitle_languages,
                        subtitle_source=subtitle_source,
                    )
                continue
            video = download_manual_media(
                db,
                video_url,
                media_type,
                download_transcript,
                subtitle_languages=subtitle_languages,
                subtitle_source=subtitle_source,
                video_quality=video_quality,
            )
        if video is None:
            raise ValueError("Aucun format à télécharger.")
        if category_labels is not None:
            video.category_labels = category_labels
            db.commit()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "downloaded"
            job.message = f"{video.title} a été téléchargé."
            job.video_id = video.id
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "failed"
            job.message = str(exc)
            db.commit()
    finally:
        db.close()


@logged_job("transcript_retry")
def run_transcript_retry_job(job_id: int, video_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Récupération du transcript en cours..."
        db.commit()

        video = db.get(Video, video_id)
        if video is None:
            raise ValueError("Vidéo introuvable.")
        video = retry_transcript_download(db, video)
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "downloaded"
            job.message = "Transcript récupéré."
            job.video_id = video.id
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "failed"
            job.message = str(exc)
            db.commit()
    finally:
        db.close()


@logged_job("channel_metadata_import")
def run_channel_metadata_import_job(
    job_id: int,
    channel_id: int,
    page: int = 1,
    section: str = "videos",
    mark_new: bool = False,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        channel = db.get(Channel, channel_id)
        if job is None:
            return
        if channel is None:
            job.status = "failed"
            job.message = "Chaîne introuvable."
            db.commit()
            return

        if job.status == "cancelled":
            return
        job.status = "running"
        section_label = "shorts" if section in {"short", "shorts"} else "vidéos"
        job.message = f"Import des métadonnées {section_label} de {channel.name} en cours..."
        db.commit()

        page = max(page, 1)
        scan_options = {
            "page": page,
            "page_size": CHANNEL_VIDEO_PAGE_SIZE,
            "max_pages": 1,
            "section": section,
        }
        if mark_new:
            scan_options["mark_new"] = True

        def should_stop() -> bool:
            # A column query reads the committed value; `db.get` would return the cached row.
            return (
                db.scalar(select(DownloadJob.status).where(DownloadJob.id == job_id)) == "cancelled"
            )

        imported = scan_channel_section(db, channel, should_stop=should_stop, **scan_options)
        job = db.get(DownloadJob, job_id)
        if job:
            db.refresh(job)
            plural = "s" if imported != 1 else ""
            if job.status == "cancelled":
                job.message = f"Exploration arrêtée : {imported} fiche{plural} {section_label} importée{plural} pour {channel.name}."
            else:
                job.status = "metadata"
                job.message = f"{imported} fiche{plural} {section_label} importée{plural} pour {channel.name}."
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job:
            job.status = "failed"
            job.message = f"Import des métadonnées échoué: {exc}"
            db.commit()
    finally:
        db.close()
