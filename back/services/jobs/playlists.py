"""Background jobs of a playlist import, from a YouTube playlist URL or a Google Takeout CSV.

`queue_*` create the playlist and the queued job a route answers with; the route then hands the
matching `run_*` to its background tasks.
"""

from typing import Any

from sqlalchemy.orm import Session

from back.core.logging import logged_job
from back.db.session import SessionLocal
from back.models.job import DownloadJob
from back.models.playlist import Playlist
from back.services.common.job_log import log_job
from back.services.ingest.throttle import RateLimitedError
from back.services.playlists.editing import create_playlist, playlist_title_from_filename
from back.services.playlists.imports import (
    MAX_PLAYLIST_IMPORT_PAGES,
    PLAYLIST_IMPORT_PAGE_SIZE,
    extract_playlist_info,
    import_playlist_entry,
    list_playlist_entries,
    parse_playlist_csv,
    playlist_import_summary,
)


class PlaylistNotRefreshableError(ValueError):
    pass


def _queue_import(db: Session, playlist: Playlist) -> DownloadJob:
    return log_job(db, "queued", f"Import de la playlist {playlist.title} en file d'attente.")


def queue_playlist_url_import(
    db: Session, url: str, title: str = ""
) -> tuple[Playlist, DownloadJob]:
    """Resolve the URL now (PlaylistNotFoundError), create the playlist, queue the import of its
    videos; run it with `run_playlist_url_import_job`. Without a title, YouTube's is used."""
    info = extract_playlist_info(url)
    playlist = create_playlist(
        db,
        title.strip() or info["title"],
        source="url",
        source_url=info["url"],
        yt_playlist_id=info.get("yt_playlist_id"),
    )
    return playlist, _queue_import(db, playlist)


def queue_playlist_csv_import(
    db: Session, content: bytes, filename: str | None, title: str = ""
) -> tuple[Playlist, DownloadJob, list[dict[str, Any]]]:
    """Read the CSV now (PlaylistCsvError), create the playlist, queue the import of its rows;
    run it with `run_playlist_csv_import_job`. Without a title, the file name gives one."""
    rows = parse_playlist_csv(content)
    playlist = create_playlist(
        db,
        title.strip() or playlist_title_from_filename(filename or "Playlist importée"),
        source="csv",
    )
    return playlist, _queue_import(db, playlist), rows


def queue_playlist_refresh(db: Session, playlist: Playlist) -> DownloadJob:
    """A new URL import that appends the playlist's new videos; run `run_playlist_url_import_job`."""
    if playlist.source != "url" or not playlist.source_url:
        raise PlaylistNotRefreshableError(
            "Seule une playlist importée depuis une URL peut être rafraîchie."
        )
    return _queue_import(db, playlist)


@logged_job("playlist_url_import")
def run_playlist_url_import_job(job_id: int, playlist_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        playlist = db.get(Playlist, playlist_id)
        if job is None:
            return
        if playlist is None or not playlist.source_url:
            job.status = "failed"
            job.message = "Playlist introuvable."
            db.commit()
            return

        job.status = "running"
        job.message = f"Import de la playlist {playlist.title} en cours..."
        db.commit()

        imported = 0
        fetched = 0
        rate_limited = False
        page = 1
        while page <= MAX_PLAYLIST_IMPORT_PAGES and not rate_limited:
            try:
                entries = list_playlist_entries(
                    playlist.source_url, page=page, page_size=PLAYLIST_IMPORT_PAGE_SIZE
                )
            except Exception as exc:
                log_job(db, "failed", f"Échec de la lecture de la playlist: {exc}")
                break
            if not entries:
                break

            # Playlists mix old/new videos in arbitrary order (unlike a
            # channel's newest-first feed), so unlike scan_channel_section
            # this must keep going past already-known videos, not stop.
            for entry in entries:
                yt_video_id = entry.get("id")
                if not yt_video_id:
                    continue
                video_url = entry.get("url") or f"https://www.youtube.com/watch?v={yt_video_id}"
                if not video_url.startswith("http"):
                    video_url = f"https://www.youtube.com/watch?v={yt_video_id}"
                try:
                    _, was_fetched = import_playlist_entry(
                        db, playlist, yt_video_id, video_url, preview=entry, pace=fetched > 0
                    )
                    fetched += was_fetched
                    imported += 1
                except RateLimitedError as exc:
                    db.rollback()
                    log_job(db, "failed", f"Import de la playlist interrompu: {exc}")
                    rate_limited = True
                    break
                except Exception as exc:
                    db.rollback()
                    log_job(db, "failed", f"Échec de l'import d'une vidéo de la playlist: {exc}")
            page += 1

        finish_playlist_import(db, job_id, playlist, imported, rate_limited)
    except Exception as exc:
        fail_playlist_import(db, job_id, exc)
    finally:
        db.close()


@logged_job("playlist_csv_import")
def run_playlist_csv_import_job(job_id: int, playlist_id: int, rows: list[dict[str, Any]]) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        playlist = db.get(Playlist, playlist_id)
        if job is None:
            return
        if playlist is None:
            job.status = "failed"
            job.message = "Playlist introuvable."
            db.commit()
            return

        job.status = "running"
        job.message = f"Import de la playlist {playlist.title} en cours..."
        db.commit()

        imported = 0
        fetched = 0
        rate_limited = False
        for row in rows:
            yt_video_id = row.get("yt_video_id")
            if not yt_video_id:
                continue
            video_url = f"https://www.youtube.com/watch?v={yt_video_id}"
            try:
                _, was_fetched = import_playlist_entry(
                    db,
                    playlist,
                    yt_video_id,
                    video_url,
                    added_at=row.get("added_at"),
                    pace=fetched > 0,
                )
                fetched += was_fetched
                imported += 1
            except RateLimitedError as exc:
                db.rollback()
                log_job(db, "failed", f"Import de la playlist interrompu: {exc}")
                rate_limited = True
                break
            except Exception as exc:
                db.rollback()
                log_job(db, "warning", f"Vidéo ignorée (introuvable ou privée): {exc}")

        finish_playlist_import(db, job_id, playlist, imported, rate_limited)
    except Exception as exc:
        fail_playlist_import(db, job_id, exc)
    finally:
        db.close()


def finish_playlist_import(
    db: Session, job_id: int, playlist: Playlist, imported: int, rate_limited: bool
) -> None:
    job = db.get(DownloadJob, job_id)
    if job:
        job.status, job.message = playlist_import_summary(playlist, imported, rate_limited)
        db.commit()


def fail_playlist_import(db: Session, job_id: int, exc: Exception) -> None:
    db.rollback()
    job = db.get(DownloadJob, job_id)
    if job:
        job.status = "failed"
        job.message = f"Import de la playlist échoué: {exc}"
        db.commit()
