"""The Recherche section of the Bibliothèque: YouTube videos for a query, each with its fiche
when the library already has it."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.video import Video
from back.services.youtube.video_search import search_videos
from back.services.youtube.yt import YoutubeSearchError


def youtube_video_candidates(db: Session, query: str) -> list[dict]:
    """YouTube videos matching `query`, each with the library's fiche when it is already there
    (`existing`, else None); raises `YoutubeSearchError` when YouTube fails."""
    if not query.strip():
        return []
    try:
        results = search_videos(query)
    except Exception as exc:
        raise YoutubeSearchError(f"Recherche YouTube impossible : {exc}") from exc
    ids = [result["yt_video_id"] for result in results]
    known = (
        {
            video.yt_video_id: video
            for video in db.scalars(select(Video).where(Video.yt_video_id.in_(ids)))
        }
        if ids
        else {}
    )
    return [{**result, "existing": known.get(result["yt_video_id"])} for result in results]
