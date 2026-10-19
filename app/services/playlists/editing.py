"""Editing a playlist and its items, shared by the playlist pages and the import jobs."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.common.categories import serialized_category_labels
from app.services.common.settings import add_video_category_labels


def next_item_position(db: Session, playlist_id: int) -> int:
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


def add_video_to_playlist(
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
            position=next_item_position(db, playlist_id),
            added_at=added_at,
        )
    )
    playlist = db.get(Playlist, playlist_id)
    video = db.get(Video, video_id)
    if playlist is not None and video is not None:
        inherit_playlist_labels(playlist, video)
    db.commit()


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


_CSV_TITLE_PREFIXES = ("vidéos de ", "videos de ", "videos from ")
PLAYLIST_SORTS = ("added", "duration", "title", "reverse")


def playlist_title_from_filename(filename: str) -> str:
    """Default title of a playlist imported from a CSV file named "Vidéos de X.csv": "X"."""
    stem = Path(filename).stem.strip()
    lowered = stem.lower()
    for prefix in _CSV_TITLE_PREFIXES:
        if lowered.startswith(prefix):
            return stem[len(prefix) :].strip() or stem
    return stem or "Playlist importée"


def create_playlist(db: Session, title: str, source: str = "manual", **fields) -> Playlist:
    playlist = Playlist(title=title, source=source, **fields)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist


def delete_playlist(db: Session, playlist: Playlist) -> None:
    db.delete(playlist)
    db.commit()


def rename_playlist(db: Session, playlist: Playlist, title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("Le titre est obligatoire.")
    playlist.title = title[:500]
    db.commit()


def set_playlist_categories(db: Session, playlist: Playlist, labels: list[str]) -> int:
    """Store the playlist's labels and copy them to its videos without any; returns how many."""
    playlist.category_labels = serialized_category_labels(labels)
    add_video_category_labels(db, labels)
    labelled = apply_playlist_labels(db, playlist)
    db.commit()
    return labelled


def set_free_listening(db: Session, playlist: Playlist, enabled: bool) -> None:
    playlist.free_listening = enabled
    db.commit()


def _duration_seconds(video: Video) -> int:
    # The column, not metadata.json: a playlist can hold hundreds of videos and the file is a ~140 KB dump.
    return video.duration_seconds or 0


def _ordered_items(db: Session, playlist_id: int) -> list[PlaylistItem]:
    return list(
        db.scalars(
            select(PlaylistItem)
            .where(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position)
        )
    )


def sort_playlist(db: Session, playlist: Playlist, by: str) -> None:
    if by not in PLAYLIST_SORTS:
        raise ValueError("Tri inconnu")
    items = _ordered_items(db, playlist.id)
    if by == "added":
        items.sort(
            key=lambda item: (
                (item.added_at or item.created_at).timestamp()
                if (item.added_at or item.created_at)
                else 0
            )
        )
    elif by == "duration":
        items.sort(key=lambda item: _duration_seconds(item.video))
    elif by == "title":
        items.sort(key=lambda item: item.video.title.casefold())
    else:
        items.reverse()
    apply_item_order(db, playlist, [item.id for item in items])


def videos_missing_media(playlist: Playlist, media_type: str) -> list[Video]:
    """The playlist's videos without a file of `media_type` ("audio" or "video")."""
    path_field = "audio_path" if media_type == "audio" else "video_path"
    return [item.video for item in playlist.items if not getattr(item.video, path_field)]


def remove_item(db: Session, item: PlaylistItem) -> None:
    """Remove an item and renumber the rest 1..n, so positions stay without gaps."""
    playlist_id = item.playlist_id
    db.delete(item)
    db.commit()
    for index, remaining_item in enumerate(_ordered_items(db, playlist_id), start=1):
        remaining_item.position = index
    db.commit()


def move_item(db: Session, item: PlaylistItem, direction: str) -> None:
    """Swap an item with its neighbour, "up" or down; nothing at either end."""
    items = _ordered_items(db, item.playlist_id)
    index = next((i for i, current in enumerate(items) if current.id == item.id), None)
    if index is None:
        return
    swap_index = index - 1 if direction == "up" else index + 1
    if 0 <= swap_index < len(items):
        items[index].position, items[swap_index].position = (
            items[swap_index].position,
            items[index].position,
        )
        db.commit()
