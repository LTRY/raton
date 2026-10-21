"""Validation of the options of a manual download (formats, subtitles, quality)."""


def normalize_download_media_types(media_type: str | list[str]) -> list[str]:
    media_types = [media_type] if isinstance(media_type, str) else list(media_type)
    normalized = []
    for item in media_types:
        if item not in {"video", "audio", "metadata"}:
            raise ValueError("Le format doit être vidéo, audio ou métadonnées.")
        if item not in normalized:
            normalized.append(item)
    if not normalized:
        raise ValueError("Sélectionne au moins un format.")
    if any(item in normalized for item in ("video", "audio")) and "metadata" not in normalized:
        normalized.append("metadata")
    return normalized


def normalize_subtitle_language(value: str) -> str | None:
    """Empty means "no language imposed": the original track is chosen by `choose_subtitle_track`."""
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not all(char.isalnum() or char in "-_" for char in normalized):
        raise ValueError("Langue de sous-titres invalide.")
    return normalized


def normalize_subtitle_source(value: str) -> str:
    if value not in {"auto", "manual", "both", "none"}:
        raise ValueError("Source de sous-titres invalide.")
    return value


def normalize_video_quality(value: str) -> str:
    if value not in {"360", "480", "720", "1080", "1440", "2160", "best"}:
        raise ValueError("Qualité vidéo invalide.")
    return value
