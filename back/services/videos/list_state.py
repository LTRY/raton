"""Vu/Écartée state of a fiche card: the stored choice, else the one deduced from playback."""

from back.models.video import Video
from back.services.common.categories import parse_video_category_labels

VIDEO_LIST_STATES = ("watched", "unwatched", "hidden")


def video_auto_list_state(playback: dict | None, is_replay_category: bool) -> str:
    """État déduit de la seule progression de lecture, sans forçage manuel."""
    if playback and playback.get("is_completed") and not is_replay_category:
        return "watched"
    return "normal"


def video_list_state(video: Video, playback: dict | None, is_replay_category: bool) -> str:
    """État de grisage effectif d'une carte vidéo : normal, watched ou hidden."""
    stored = video.list_state
    if stored == "hidden":
        return "hidden"
    if stored == "watched":
        return "watched"
    if stored == "unwatched":
        return "normal"
    return video_auto_list_state(playback, is_replay_category)


def card_list_states(
    video: Video, playback: dict | None, no_progress_labels: set[str]
) -> tuple[str, str, bool]:
    """(shown state, state deduced from playback, replay category) of a fiche's card.

    A fiche in a "no progress bar" category (music...) is replayed, never done: no progress bar
    and no automatic Vu.
    """
    replay = bool(
        no_progress_labels.intersection(parse_video_category_labels(video.category_labels))
    )
    return (
        video_list_state(video, playback, replay),
        video_auto_list_state(playback, replay),
        replay,
    )
