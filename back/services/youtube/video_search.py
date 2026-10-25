"""YouTube's own video search, read with yt-dlp, without touching the fiches."""

from typing import Any

from yt_dlp import YoutubeDL

from back.services.youtube.yt import ytdlp_call

VIDEO_SEARCH_LIMIT = 20


def video_thumbnail_url(entry: dict[str, Any], yt_video_id: str) -> str:
    # A flat search entry lists its thumbnails smallest first; YouTube serves a fixed URL anyway.
    thumbnails = [item.get("url") for item in entry.get("thumbnails") or [] if item.get("url")]
    url = thumbnails[-1] if thumbnails else f"https://i.ytimg.com/vi/{yt_video_id}/mqdefault.jpg"
    return f"https:{url}" if url.startswith("//") else url


def search_videos(query: str, limit: int = VIDEO_SEARCH_LIMIT) -> list[dict[str, Any]]:
    """YouTube videos matching a free-text query, in YouTube's own relevance order."""
    value = " ".join(query.split())
    if not value:
        return []
    opts = {"quiet": True, "skip_download": True, "extract_flat": True}
    with ytdlp_call("search_videos"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{value}", download=False)
    results = []
    for entry in (info.get("entries") if isinstance(info, dict) else None) or []:
        yt_video_id = str((entry or {}).get("id") or "")
        # `ytsearch` asks for videos only, but a channel or a playlist can still slip in.
        if len(yt_video_id) != 11:
            continue
        url = entry.get("url") or ""
        results.append(
            {
                "yt_video_id": yt_video_id,
                "title": entry.get("title") or yt_video_id,
                "url": f"https://www.youtube.com/watch?v={yt_video_id}",
                "channel_name": entry.get("channel") or entry.get("uploader"),
                "yt_channel_id": entry.get("channel_id"),
                "duration_seconds": int(entry["duration"]) if entry.get("duration") else None,
                "view_count": entry.get("view_count"),
                "is_short": "/shorts/" in url,
                "thumbnail_url": video_thumbnail_url(entry, yt_video_id),
            }
        )
    return results
