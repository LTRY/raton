"""The record a `/api` path names, or a 404 carrying the service's French message."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.channels.lookup import ChannelNotInLibraryError, find_library_channel
from app.services.playlists.editing import (
    PlaylistItemNotFoundError,
    PlaylistNotInLibraryError,
    find_playlist,
    find_playlist_item,
)
from app.services.videos.detail_view import VideoNotFoundError, find_video


def fiche(db: Session, video_id: int) -> Video:
    try:
        return find_video(db, video_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def library_channel(db: Session, channel_id: int) -> Channel:
    try:
        return find_library_channel(db, channel_id)
    except ChannelNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def library_playlist(db: Session, playlist_id: int) -> Playlist:
    try:
        return find_playlist(db, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def playlist_item(db: Session, playlist_id: int, item_id: int) -> PlaylistItem:
    try:
        return find_playlist_item(db, playlist_id, item_id)
    except PlaylistItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
