"""Demo data for throwaway instances (PR previews).

Run as `python -m scripts.demo_seed` against an empty sqlite database: it
creates the tables and a handful of channels and videos, then does nothing on
the following runs. No media files exist behind these rows, so players have
nothing to play, but every list and detail page has something to show.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.db.base import *  # noqa: F403  (registers every model on Base.metadata)
from back.db.session import Base, SessionLocal, engine
from back.models.channel import Channel
from back.models.video import Video

DEMO_CHANNELS = [
    ("Atelier du code", "UCdemo000000000000000001", True),
    ("Carnets de cuisine", "UCdemo000000000000000002", False),
    ("Chroniques d'histoire", "UCdemo000000000000000003", True),
]

DEMO_TITLES = [
    "Introduction aux tests automatisés",
    "Refactoriser sans peur",
    "Pâte à pizza : le secret de l'hydratation",
    "Le pain au levain en cinq étapes",
    "La chute de l'Empire romain d'Occident",
    "Une brève histoire du calendrier",
    "Optimiser une requête SQL lente",
    "Cuisson basse température : mythes et réalités",
    "Comment on lisait les cartes au Moyen Âge",
]


def seed_demo(db: Session) -> bool:
    """Insert the demo rows; return False when the database already has channels."""
    if db.scalar(select(Channel.id).limit(1)) is not None:
        return False
    now = datetime.now(UTC)
    channels = []
    for name, yt_channel_id, bell in DEMO_CHANNELS:
        channel = Channel(
            url=f"https://www.youtube.com/channel/{yt_channel_id}",
            name=name,
            yt_channel_id=yt_channel_id,
            auto_metadata_enabled=bell,
            rating=3,
        )
        db.add(channel)
        channels.append(channel)
    db.flush()
    for index, title in enumerate(DEMO_TITLES):
        channel = channels[index % len(channels)]
        yt_video_id = f"demo{index:07d}"
        db.add(
            Video(
                channel_id=channel.id,
                yt_video_id=yt_video_id,
                title=title,
                url=f"https://www.youtube.com/watch?v={yt_video_id}",
                folder_path=f"/tmp/media/{channel.name}/{yt_video_id}",
                published_at=now - timedelta(days=index * 3 + 1),
                downloaded_at=now - timedelta(days=index),
                duration_seconds=300 + index * 217,
                view_count=1_000 * (index + 1),
                is_new=index < 3,
            )
        )
    db.commit()
    return True


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
