"""The card of a fiche in every `/api` list (library, Nouveautés, channel page, history).

One builder so that every list shows the same fields; the user's state and latest playback of
the whole page are read in one query each (`library_cards`).
"""

from sqlalchemy.orm import Session

from back.models.video import Video
from back.schemas.library import CardPlaybackRead, LibraryVideoRead
from back.schemas.video import VideoRead
from back.services.common.settings import get_no_progress_category_labels
from back.services.videos.library_view import library_cards
from back.services.videos.list_state import card_list_states


def card_read(card: dict, no_progress_labels: set[str]) -> LibraryVideoRead:
    video = card["video"]
    state = card["state"]
    playback = card["playback"]
    shown_state, auto_state, replay = card_list_states(video, state, playback, no_progress_labels)
    return LibraryVideoRead(
        **VideoRead.of(video, state.rating).model_dump(),
        channel_name=card["channel_name"],
        duration_seconds=video.duration_seconds,
        view_count=video.view_count,
        is_new=state.is_new,
        list_state=state.list_state,
        # Both paths can be set at once: check each column, never media_type.
        has_video=video.video_path is not None,
        has_audio=video.audio_path is not None,
        has_thumbnail=video.thumbnail_path is not None,
        playback=CardPlaybackRead(**playback) if playback else None,
        shown_state=shown_state,
        auto_state=auto_state,
        replay_category=replay,
    )


def card_reads(db: Session, user_id: int, videos: list[Video]) -> list[LibraryVideoRead]:
    no_progress_labels = set(get_no_progress_category_labels(db))
    return [card_read(card, no_progress_labels) for card in library_cards(db, user_id, videos)]
