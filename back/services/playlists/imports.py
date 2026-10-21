import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from yt_dlp import YoutubeDL

from back.models.playlist import Playlist
from back.models.video import Video
from back.services.common.job_log import log_job
from back.services.ingest.metadata_import import import_video_metadata
from back.services.ingest.throttle import pause_between_imports
from back.services.playlists.editing import add_video_to_playlist
from back.services.youtube.url_guard import UnsafeUrlError, ensure_public_http_url

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


def import_playlist_entry(
    db: Session,
    playlist: Playlist,
    yt_video_id: str,
    video_url: str,
    *,
    preview: dict[str, Any] | None = None,
    added_at: datetime | None = None,
    pace: bool = False,
) -> tuple[Video, bool]:
    """Add one video to the playlist, importing its fiche first when the library lacks it.

    Returns the fiche and whether it was fetched from YouTube. Only a real fetch is paced
    (`pace` is False for the first one of a run): a known video costs no request.
    """
    video = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    fetched = video is None
    if fetched:
        if pace:
            pause_between_imports()
        video = import_video_metadata(
            db,
            video_url,
            channel_id=None,
            preview=preview,
            download_source="auto",
            source_section="videos",
            is_new=False,
        )
    add_video_to_playlist(db, playlist.id, video.id, added_at=added_at)
    log_job(db, "metadata", f"Ajouté à la playlist: {video.title}", video_id=video.id)
    return video, fetched


def playlist_import_summary(
    playlist: Playlist, imported: int, rate_limited: bool
) -> tuple[str, str]:
    """Final (status, message) of a playlist import job."""
    plural = "s" if imported != 1 else ""
    if rate_limited:
        return (
            "failed",
            f"Import interrompu: YouTube limite les requêtes (HTTP 429). {imported} vidéo{plural} "
            f"importée{plural} pour la playlist {playlist.title}; relancer l'import plus tard "
            "reprendra les vidéos restantes.",
        )
    return (
        "metadata",
        f"{imported} vidéo{plural} importée{plural} pour la playlist {playlist.title}.",
    )


def playlist_to_csv(playlist: Playlist) -> str:
    """Google Takeout per-playlist layout, so ``parse_playlist_csv`` can read it back."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["ID vidéo", "Code temporel de création de la vidéo de la playlist"])
    for item in playlist.items:
        stamp = item.added_at or item.created_at
        writer.writerow([item.video.yt_video_id, stamp.isoformat() if stamp else ""])
    return buffer.getvalue()
