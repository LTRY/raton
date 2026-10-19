"""Vu/Écartée state of a fiche card: the stored choice, else the one deduced from playback."""

from app.models.video import Video

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
