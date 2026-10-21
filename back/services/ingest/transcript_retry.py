"""New attempt at the subtitles of a fiche that has none, or the wrong ones."""

from pathlib import Path

from sqlalchemy.orm import Session

from back.models.video import Video
from back.services.common.files import remove_directory
from back.services.ingest.staging import final_path, merge_staged_files, staged_folder
from back.services.youtube.downloads import (
    SUBTITLE_EXTENSIONS,
    discover_downloaded_files,
    download_subtitles,
    write_transcript,
)


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
