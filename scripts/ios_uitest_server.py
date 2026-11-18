"""The back of the iOS UI tests (`ios/RatonUITests`): the demo data, and a YouTube that needs no network.

Run by `scripts/ios_uitest_server.sh`. The search answers with the same three videos for any query,
and the import of a video (what a star on a video that is not indexed triggers) creates its fiche
without yt-dlp, so the tests give the same result on a CI runner as on a laptop.
"""

import re
from datetime import UTC, datetime

import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.video import Video
from back.services.jobs import downloads
from back.services.videos import youtube_search

STUB_CHANNEL_ID = "UCstub0000000000000000001"
STUB_VIDEOS = [
    {"yt_video_id": f"stubvideo{index:02d}", "title": f"Vidéo de test {index}"}
    for index in (1, 2, 3)
]


def fake_search(query: str, limit: int = 20) -> list[dict]:
    return [
        {
            **video,
            "url": f"https://www.youtube.com/watch?v={video['yt_video_id']}",
            "channel_name": "Chaîne de test",
            "yt_channel_id": STUB_CHANNEL_ID,
            "duration_seconds": 600,
            "view_count": 1234,
            "published_at": datetime.now(UTC),
            "is_short": False,
            "thumbnail_url": "http://127.0.0.1:1/thumbnail.jpg",
        }
        for video in STUB_VIDEOS
    ]


def fake_import(db: Session, video_url: str, **_options) -> Video:
    match = re.search(r"v=([\w-]{11})", video_url)
    if match is None:
        raise ValueError("Lien YouTube inconnu.")
    yt_video_id = match.group(1)
    known = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
    if known is not None:
        return known
    channel = db.scalar(select(Channel).where(Channel.yt_channel_id == STUB_CHANNEL_ID))
    if channel is None:
        channel = Channel(
            url=f"https://www.youtube.com/channel/{STUB_CHANNEL_ID}",
            name="Chaîne de test",
            yt_channel_id=STUB_CHANNEL_ID,
        )
        db.add(channel)
        db.flush()
    title = next((v["title"] for v in STUB_VIDEOS if v["yt_video_id"] == yt_video_id), yt_video_id)
    video = Video(
        channel_id=channel.id,
        yt_video_id=yt_video_id,
        title=title,
        url=video_url,
        folder_path=f"/tmp/raton-uitest/{yt_video_id}",
        published_at=datetime.now(UTC),
        duration_seconds=600,
        view_count=1234,
    )
    db.add(video)
    db.commit()
    return video


# Through the modules where the names are looked up.
youtube_search.search_videos = fake_search
downloads.import_video_metadata = fake_import

if __name__ == "__main__":
    from back.main import app

    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
