"""Vu/Écartée state of a fiche card for one user: their stored choice, else the one deduced
from their playback."""

from back.models.user import UserVideo
from back.models.video import Video
from back.services.common.categories import parse_video_category_labels

VIDEO_LIST_STATES = ("watched", "unwatched", "hidden")


def video_auto_list_state(playback: dict | None, is_replay_category: bool) -> str:
    """State deduced from playback progress alone, without a manual choice."""
    if playback and playback.get("is_completed") and not is_replay_category:
        return "watched"
    return "normal"


def video_list_state(state: UserVideo, playback: dict | None, is_replay_category: bool) -> str:
    """Effective greying of a fiche card: normal, watched or hidden."""
    stored = state.list_state
    if stored == "hidden":
        return "hidden"
    if stored == "watched":
        return "watched"
    if stored == "unwatched":
        return "normal"
    return video_auto_list_state(playback, is_replay_category)


def card_list_states(
    video: Video, state: UserVideo, playback: dict | None, no_progress_labels: set[str]
) -> tuple[str, str, bool]:
    """(shown state, state deduced from playback, replay category) of a fiche's card.

    `state` and `playback` are the user's own. A fiche in a "no progress bar" category
    (music...) is replayed, never done: no progress bar and no automatic Vu.
    """
    replay = bool(
        no_progress_labels.intersection(parse_video_category_labels(video.category_labels))
    )
    return (
        video_list_state(state, playback, replay),
        video_auto_list_state(playback, replay),
        replay,
    )
