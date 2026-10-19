"""What yt-dlp says about a channel: which channel a URL or handle names, its profile, its videos."""

from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse

from yt_dlp import YoutubeDL

from app.models.channel import Channel
from app.services.youtube.url_guard import UnsafeUrlError, ensure_public_http_url
from app.services.youtube.yt import _ytdlp_call

CHANNEL_SECTIONS = {"videos", "shorts"}
CHANNEL_SECTION_ALIASES = {
    "video": "videos",
    "videos": "videos",
    "short": "shorts",
    "shorts": "shorts",
}
# YouTube's own "Type: Channel" search filter, as the `sp` query parameter.
CHANNEL_SEARCH_FILTER = "EgIQAg%3D%3D"
CHANNEL_SEARCH_LIMIT = 8


class ChannelNotFoundError(ValueError):
    pass


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc) or value.startswith(
        ("www.", "youtube.com/", "youtu.be/")
    )


def looks_like_channel_handle(value: str) -> bool:
    return value.startswith("@")


def looks_like_bare_channel_handle(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("@")
        and all(char.isalnum() or char in "._-" for char in value)
    )


def resolve_channel_url(channel_input: str) -> str:
    value = channel_input.strip()
    if looks_like_channel_handle(value):
        handle = value[1:]
        if not handle or any(char.isspace() for char in handle) or "/" in handle:
            raise ChannelNotFoundError(f"Chaîne introuvable pour {value}")
        return f"https://www.youtube.com/{value}"

    if looks_like_url(value):
        if value.startswith(("www.", "youtube.com/", "youtu.be/")):
            return f"https://{value}"
        try:
            return ensure_public_http_url(value)
        except UnsafeUrlError as exc:
            raise ChannelNotFoundError(str(exc)) from exc

    if looks_like_bare_channel_handle(value):
        return f"https://www.youtube.com/@{value}"

    # A free-text name is ambiguous: callers offer `search_channels` candidates
    # instead of letting a guess pick the channel.
    raise ChannelNotFoundError(f"Chaîne introuvable pour {value}")


def is_channel_reference(value: str) -> bool:
    """Whether the input designates one channel (URL or @handle) rather than a name to search."""
    value = value.strip()
    return looks_like_url(value) or looks_like_channel_handle(value)


def search_channels(query: str, limit: int = CHANNEL_SEARCH_LIMIT) -> list[dict[str, Any]]:
    """YouTube channels matching a free-text name, in YouTube's own relevance order."""
    value = query.strip()
    if not value:
        return []
    url = f"https://www.youtube.com/results?search_query={quote_plus(value)}&sp={CHANNEL_SEARCH_FILTER}"
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": limit}
    with _ytdlp_call("search_channels"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    results = []
    for entry in (info.get("entries") if isinstance(info, dict) else None) or []:
        channel_id = str((entry or {}).get("id") or "")
        # The filter is only a request: skip anything that is not a channel.
        if not channel_id.startswith("UC"):
            continue
        handle = entry.get("uploader_id")
        handle = handle if isinstance(handle, str) and handle.startswith("@") else None
        thumbnail = next(
            (item.get("url") for item in entry.get("thumbnails") or [] if item.get("url")), None
        )
        if thumbnail and thumbnail.startswith("//"):
            thumbnail = f"https:{thumbnail}"
        results.append(
            {
                "yt_channel_id": channel_id,
                "name": entry.get("channel") or entry.get("title") or handle or channel_id,
                "handle": handle,
                "url": f"https://www.youtube.com/{handle}"
                if handle
                else f"https://www.youtube.com/channel/{channel_id}",
                "subscriber_count": entry.get("channel_follower_count"),
                "description": (entry.get("description") or "").strip() or None,
                "thumbnail_url": thumbnail,
            }
        )
    return results


def extract_channel_info(channel_input: str) -> dict[str, Any]:
    submitted_value = channel_input.strip()
    strict_handle = looks_like_channel_handle(submitted_value) or looks_like_bare_channel_handle(
        submitted_value
    )
    url = resolve_channel_url(channel_input)
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": 1}
    try:
        with _ytdlp_call("extract_channel_info"), YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        if strict_handle:
            raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_input.strip()}") from exc
        raise
    if not info:
        raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_input.strip()}")
    return {
        "url": url,
        "name": info.get("channel") or info.get("uploader") or info.get("title") or url,
        "yt_channel_id": info.get("channel_id") or info.get("uploader_id") or info.get("id"),
    }


def channel_image_url(thumbnails: list[dict[str, Any]] | None, image_id: str) -> str | None:
    # The uncropped entries are the originals; the numbered ones are crops of them.
    for item in thumbnails or []:
        if item.get("id") == image_id and item.get("url"):
            url = item["url"]
            return f"https:{url}" if url.startswith("//") else url
    return None


def fetch_channel_profile(channel_url: str) -> dict[str, Any]:
    """Description, tags and image URLs of a channel, from the same flat extraction used to add it."""
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": 1}
    with _ytdlp_call("fetch_channel_profile"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    if not info:
        raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_url}")
    thumbnails = info.get("thumbnails")
    return {
        "description": (info.get("description") or "").strip() or None,
        "keywords": [
            tag.strip() for tag in info.get("tags") or [] if isinstance(tag, str) and tag.strip()
        ],
        "avatar_url": channel_image_url(thumbnails, "avatar_uncropped"),
        "banner_url": channel_image_url(thumbnails, "banner_uncropped"),
    }


def count_channel_entries(channel: Channel) -> int | None:
    def count_from_info(info: dict[str, Any]) -> int | None:
        for key in ("playlist_count", "n_entries"):
            value = info.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        return None

    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playlistend": 1,
    }
    with _ytdlp_call("count_channel_entries"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel.url, download=False)

    count = count_from_info(info)
    if count is not None:
        return count

    full_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    with _ytdlp_call("count_channel_entries"), YoutubeDL(full_opts) as ydl:
        info = ydl.extract_info(channel.url, download=False)

    count = count_from_info(info)
    if count is not None:
        return count
    entries = info.get("entries")
    return len([entry for entry in entries if entry]) if isinstance(entries, list) else None


def normalized_channel_section(section: str = "videos") -> str:
    normalized = CHANNEL_SECTION_ALIASES.get(section)
    if normalized is None:
        raise ValueError("section must be videos or shorts")
    return normalized


def channel_section_url(url: str, section: str = "videos") -> str:
    section = normalized_channel_section(section)
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and segments[-1] in CHANNEL_SECTIONS:
        segments = segments[:-1]
    path = "/" + "/".join([*segments, section])
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def list_channel_entries(
    channel: Channel, page: int = 1, page_size: int = 25, section: str = "videos"
) -> list[dict[str, Any]]:
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if page_size < 1:
        raise ValueError("page_size must be greater than or equal to 1")

    section_url = channel_section_url(channel.url, section)
    playlist_start = ((page - 1) * page_size) + 1
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playliststart": playlist_start,
        "playlistend": playlist_start + page_size - 1,
    }
    with _ytdlp_call("list_channel_entries"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(section_url, download=False)
    return [entry for entry in info.get("entries", []) if entry]
