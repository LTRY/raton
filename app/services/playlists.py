import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from yt_dlp import YoutubeDL

from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.job import DownloadJob
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.scanner import (
    RateLimitedError,
    import_video_metadata,
    log_job,
    pause_between_imports,
)
from app.services.url_guard import UnsafeUrlError, ensure_public_http_url

MAX_PLAYLIST_IMPORT_PAGES = 40
PLAYLIST_IMPORT_PAGE_SIZE = 50


# Titles yt-dlp gives to flat entries it cannot read (no real metadata behind them).
_UNAVAILABLE_TITLES = {"[private video]", "[deleted video]"}
PREVIEW_SAMPLE_TITLES = 4
_KNOWN_LOOKUP_CHUNK = 500


class PlaylistNotFoundError(ValueError):
    pass


class PlaylistCsvError(ValueError):
    pass


def extract_playlist_info(playlist_url: str) -> dict[str, Any]:
    url = playlist_url.strip()
    if not url:
        raise PlaylistNotFoundError("URL de playlist manquante.")
    try:
        ensure_public_http_url(url)
    except UnsafeUrlError as exc:
        raise PlaylistNotFoundError(str(exc)) from exc
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": 1}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PlaylistNotFoundError(f"Playlist introuvable pour {url}") from exc
    if not info:
        raise PlaylistNotFoundError(f"Playlist introuvable pour {url}")
    return {
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or url,
        "yt_playlist_id": info.get("id"),
    }


def preview_playlist(db: Session, playlist_url: str) -> dict[str, Any]:
    """Read-only summary of a playlist, shown before the user confirms the import.

    Flat extraction gives no per-entry duration for every video, so
    `duration_seconds` is a lower bound and `unknown_duration_count` says how
    many entries it leaves out.
    """
    url = playlist_url.strip()
    if not url:
        raise PlaylistNotFoundError("URL de playlist manquante.")
    try:
        ensure_public_http_url(url)
    except UnsafeUrlError as exc:
        raise PlaylistNotFoundError(str(exc)) from exc
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playlistend": MAX_PLAYLIST_IMPORT_PAGES * PLAYLIST_IMPORT_PAGE_SIZE,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PlaylistNotFoundError(f"Playlist introuvable pour {url}") from exc
    if not info:
        raise PlaylistNotFoundError(f"Playlist introuvable pour {url}")

    entries = [entry for entry in (info.get("entries") or []) if entry]
    available = [
        entry
        for entry in entries
        if str(entry.get("title") or "").strip().lower() not in _UNAVAILABLE_TITLES
    ]
    durations = [entry.get("duration") for entry in available]
    known_durations = [
        int(value) for value in durations if isinstance(value, (int, float)) and value > 0
    ]

    video_ids = [str(entry["id"]) for entry in available if entry.get("id")]
    known_in_library = 0
    for start in range(0, len(video_ids), _KNOWN_LOOKUP_CHUNK):
        chunk = video_ids[start : start + _KNOWN_LOOKUP_CHUNK]
        known_in_library += (
            db.scalar(select(func.count()).select_from(Video).where(Video.yt_video_id.in_(chunk)))
            or 0
        )

    return {
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or url,
        "yt_playlist_id": info.get("id"),
        "channel_name": info.get("channel") or info.get("uploader"),
        "video_count": len(available),
        "unavailable_count": len(entries) - len(available),
        "duration_seconds": sum(known_durations),
        "unknown_duration_count": len(available) - len(known_durations),
        "known_in_library_count": known_in_library,
        "sample_titles": [str(entry["title"]) for entry in available if entry.get("title")][
            :PREVIEW_SAMPLE_TITLES
        ],
        "truncated": len(entries) >= MAX_PLAYLIST_IMPORT_PAGES * PLAYLIST_IMPORT_PAGE_SIZE,
    }


def list_playlist_entries(
    playlist_url: str, page: int = 1, page_size: int = 50
) -> list[dict[str, Any]]:
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if page_size < 1:
        raise ValueError("page_size must be greater than or equal to 1")

    playlist_start = ((page - 1) * page_size) + 1
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playliststart": playlist_start,
        "playlistend": playlist_start + page_size - 1,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    return [entry for entry in info.get("entries", []) if entry]


def parse_playlist_csv(content: bytes) -> list[dict[str, Any]]:
    """Parses a single Google-Takeout per-playlist CSV ("Vidéos de <Titre>.csv").

    Column position, not header text, drives parsing: header names are
    locale-dependent ("ID vidéo,Code temporel de création..." in French
    exports) so the header row is always skipped unconditionally rather
    than matched, and column 0 = video id, column 1 (optional) = ISO8601
    "added to playlist" timestamp.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PlaylistCsvError("Fichier CSV illisible (encodage non supporté).") from exc

    reader = csv.reader(io.StringIO(text))
    rows_iter = iter(reader)
    next(rows_iter, None)

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_row in rows_iter:
        if not raw_row:
            continue
        yt_video_id = (raw_row[0] or "").strip()
        if not yt_video_id or yt_video_id in seen_ids:
            continue
        seen_ids.add(yt_video_id)
        added_at = None
        if len(raw_row) > 1 and raw_row[1].strip():
            try:
                added_at = datetime.fromisoformat(raw_row[1].strip())
            except ValueError:
                added_at = None
        rows.append({"yt_video_id": yt_video_id, "added_at": added_at})

    if not rows:
        raise PlaylistCsvError("Aucune vidéo trouvée dans ce fichier.")
    return rows


def _next_position(db: Session, playlist_id: int) -> int:
    current_max = db.scalar(
        select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist_id)
    )
    return (current_max or 0) + 1


def inherit_playlist_labels(playlist: Playlist, video: Video) -> bool:
    """Give a video the playlist's labels when it has none of its own, like a channel's labels.

    The caller commits. A video that already has labels (its own, or a channel's copied earlier) keeps them,
    so the first source wins and a later playlist never overrides a label the user may have set by hand.
    """
    if playlist.category_labels and not video.category_labels:
        video.category_labels = playlist.category_labels
        return True
    return False


def apply_playlist_labels(db: Session, playlist: Playlist) -> int:
    """Copy the playlist's labels to its videos that have none; returns how many were labelled."""
    if not playlist.category_labels:
        return 0
    videos = db.scalars(
        select(Video)
        .join(PlaylistItem, PlaylistItem.video_id == Video.id)
        .where(PlaylistItem.playlist_id == playlist.id)
    )
    return sum(inherit_playlist_labels(playlist, video) for video in videos)


def _link_video_to_playlist(
    db: Session,
    playlist_id: int,
    video_id: int,
    added_at: datetime | None = None,
) -> None:
    existing = db.scalar(
        select(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist_id, PlaylistItem.video_id == video_id
        )
    )
    if existing:
        return
    db.add(
        PlaylistItem(
            playlist_id=playlist_id,
            video_id=video_id,
            position=_next_position(db, playlist_id),
            added_at=added_at,
        )
    )
    playlist = db.get(Playlist, playlist_id)
    video = db.get(Video, video_id)
    if playlist is not None and video is not None:
        inherit_playlist_labels(playlist, video)
    db.commit()


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
                    video = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
                    if video is None:
                        # Only a real fetch is paced: a known video costs no request.
                        if fetched:
                            pause_between_imports()
                        fetched += 1
                        video = import_video_metadata(
                            db,
                            video_url,
                            channel_id=None,
                            preview=entry,
                            download_source="auto",
                            source_section="videos",
                            is_new=False,
                        )
                    _link_video_to_playlist(db, playlist.id, video.id)
                    log_job(
                        db, "metadata", f"Ajouté à la playlist: {video.title}", video_id=video.id
                    )
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

        job = db.get(DownloadJob, job_id)
        if job:
            plural = "s" if imported != 1 else ""
            if rate_limited:
                job.status = "failed"
                job.message = (
                    f"Import interrompu: YouTube limite les requêtes (HTTP 429). {imported} vidéo{plural} "
                    f"importée{plural} pour la playlist {playlist.title}; relancer l'import plus tard "
                    "reprendra les vidéos restantes."
                )
            else:
                job.status = "metadata"
                job.message = (
                    f"{imported} vidéo{plural} importée{plural} pour la playlist {playlist.title}."
                )
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job:
            job.status = "failed"
            job.message = f"Import de la playlist échoué: {exc}"
            db.commit()
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
                video = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
                if video is None:
                    # Only a real fetch is paced: a known video costs no request.
                    if fetched:
                        pause_between_imports()
                    fetched += 1
                    video = import_video_metadata(
                        db,
                        video_url,
                        channel_id=None,
                        download_source="auto",
                        source_section="videos",
                        is_new=False,
                    )
                _link_video_to_playlist(db, playlist.id, video.id, added_at=row.get("added_at"))
                log_job(db, "metadata", f"Ajouté à la playlist: {video.title}", video_id=video.id)
                imported += 1
            except RateLimitedError as exc:
                db.rollback()
                log_job(db, "failed", f"Import de la playlist interrompu: {exc}")
                rate_limited = True
                break
            except Exception as exc:
                db.rollback()
                log_job(db, "warning", f"Vidéo ignorée (introuvable ou privée): {exc}")

        job = db.get(DownloadJob, job_id)
        if job:
            plural = "s" if imported != 1 else ""
            if rate_limited:
                job.status = "failed"
                job.message = (
                    f"Import interrompu: YouTube limite les requêtes (HTTP 429). {imported} vidéo{plural} "
                    f"importée{plural} pour la playlist {playlist.title}; relancer l'import plus tard "
                    "reprendra les vidéos restantes."
                )
            else:
                job.status = "metadata"
                job.message = (
                    f"{imported} vidéo{plural} importée{plural} pour la playlist {playlist.title}."
                )
            db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_id)
        if job:
            job.status = "failed"
            job.message = f"Import de la playlist échoué: {exc}"
            db.commit()
    finally:
        db.close()


def apply_item_order(db: Session, playlist: Playlist, ordered_item_ids: list[int]) -> bool:
    """Rewrites positions 1..n following ``ordered_item_ids``.

    The ids must be exactly the playlist's current items (no more, no fewer):
    a stale page that lost a race with a removal must not silently drop or
    resurrect items, so any mismatch leaves positions untouched.
    """
    by_id = {item.id: item for item in playlist.items}
    if len(ordered_item_ids) != len(by_id) or set(ordered_item_ids) != set(by_id):
        return False
    for position, item_id in enumerate(ordered_item_ids, start=1):
        by_id[item_id].position = position
    db.commit()
    return True


def duplicate_playlist(db: Session, playlist: Playlist) -> Playlist:
    """Copy as a manual playlist: the copy is detached from the YouTube/CSV source."""
    copy = Playlist(
        title=f"{playlist.title} (copie)"[:500],
        source="manual",
        category_labels=playlist.category_labels,
        free_listening=playlist.free_listening,
    )
    db.add(copy)
    db.flush()
    for item in playlist.items:
        db.add(
            PlaylistItem(
                playlist_id=copy.id,
                video_id=item.video_id,
                position=item.position,
                added_at=item.added_at,
            )
        )
    db.commit()
    db.refresh(copy)
    return copy


def playlist_to_csv(playlist: Playlist) -> str:
    """Google Takeout per-playlist layout, so ``parse_playlist_csv`` can read it back."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["ID vidéo", "Code temporel de création de la vidéo de la playlist"])
    for item in playlist.items:
        stamp = item.added_at or item.created_at
        writer.writerow([item.video.yt_video_id, stamp.isoformat() if stamp else ""])
    return buffer.getvalue()
