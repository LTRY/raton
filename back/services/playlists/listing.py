"""What the playlist pages show, as raw values: the list with its covers, a playlist's rows,
its CSV export.

Shared by `/playlists`, `/playlists/{id}` and their `/api` twins; labels are the caller's. A
playlist belongs to one user: only theirs are listed, and its rows say what they have seen.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from back.models.playlist import Playlist, PlaylistItem
from back.models.user import UserVideo
from back.models.video import Video
from back.services.common.user_state import video_states
from back.services.playlists.editing import PlaylistNotInLibraryError
from back.services.playlists.imports import playlist_to_csv


def list_playlists(db: Session, user_id: int, by_title: bool = False) -> list[Playlist]:
    """The user's playlists, newest first (or by title), items and cover videos loaded in a
    constant number of queries."""
    order = Playlist.title if by_title else Playlist.created_at.desc()
    playlists = list(
        db.scalars(
            select(Playlist)
            .where(Playlist.user_id == user_id)
            .options(selectinload(Playlist.items))
            .order_by(order)
        )
    )
    # One query for every cover, attached to its item. Relying on the identity map instead does
    # not hold: it keeps weak references, so unreferenced covers were collected and each
    # `item.video` went back to the database.
    first_items = [playlist.items[0] for playlist in playlists if playlist.items]
    if first_items:
        covers = {
            video.id: video
            for video in db.scalars(
                select(Video).where(Video.id.in_([item.video_id for item in first_items]))
            )
        }
        for item in first_items:
            set_committed_value(item, "video", covers.get(item.video_id))
    return playlists


def playlist_summary(playlist: Playlist) -> dict:
    first_item = playlist.items[0] if playlist.items else None
    return {
        "playlist": playlist,
        "item_count": len(playlist.items),
        "cover_video": first_item.video if first_item else None,
    }


def load_playlist(db: Session, user_id: int, playlist_id: int) -> Playlist:
    """The user's playlist with its items, their videos and channels, in a constant number of
    queries."""
    playlist = db.scalars(
        select(Playlist)
        .where(Playlist.id == playlist_id, Playlist.user_id == user_id)
        .options(
            selectinload(Playlist.items)
            .selectinload(PlaylistItem.video)
            .selectinload(Video.channel)
        )
        # Reread rows the session already holds: positions and items change under a reorder or
        # a removal made earlier in the same session.
        .execution_options(populate_existing=True)
    ).one_or_none()
    if playlist is None:
        raise PlaylistNotInLibraryError()
    return playlist


def playlist_row(item: PlaylistItem, state: UserVideo) -> dict:
    """`state` is the playlist owner's state on the item's fiche."""
    video = item.video
    return {
        "item": item,
        "video": video,
        "title": video.title,
        "channel_name": video.channel.name if video.channel else None,
        # The column, not metadata.json: a playlist can hold hundreds of videos and the file is
        # a ~140 KB dump.
        "duration_seconds": video.duration_seconds or 0,
        "has_audio": bool(video.audio_path),
        "has_video": bool(video.video_path),
        # Set by the 90% rule (`mark_watched_if_complete`), for the owner's playback only.
        "seen": state.watched_at is not None,
    }


def playlist_rows(db: Session, playlist: Playlist) -> list[dict]:
    """One `playlist_row` per item; the owner's states read in one query."""
    states = video_states(db, playlist.user_id, [item.video_id for item in playlist.items])
    return [playlist_row(item, states[item.video_id]) for item in playlist.items]


def playlist_stats(rows: list[dict]) -> dict[str, int]:
    return {
        "count": len(rows),
        "total_duration_seconds": sum(row["duration_seconds"] for row in rows),
        "seen_count": sum(1 for row in rows if row["seen"]),
        "missing_audio": sum(1 for row in rows if not row["has_audio"]),
        "missing_video": sum(1 for row in rows if not row["has_video"]),
    }


def playlist_csv_export(db: Session, user_id: int, playlist_id: int) -> tuple[str, str]:
    """(file name, content) of the playlist's Takeout CSV, items and videos loaded up front."""
    playlist = load_playlist(db, user_id, playlist_id)
    return f"playlist-{playlist.id}.csv", playlist_to_csv(playlist)
