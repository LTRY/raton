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
from back.services.videos.playback import record_playback_activity

DEMO_CHANNELS = [
    ("Atelier du code", "UCdemo000000000000000001", True),
    ("Carnets de cuisine", "UCdemo000000000000000002", False),
    ("Chroniques d'histoire", "UCdemo000000000000000003", True),
]

# (title, rating, list_state, share of the video already played, files the fiche holds):
# enough variety for every shape of card — one- and long multi-line titles, stars, Vu/Ecartee,
# a progress bar, and the Vidéo/Audio/Métadonnées badges Exploration filters on.
DEMO_VIDEOS = [
    ("Introduction aux tests automatisés", 0, None, 0.35, "video"),
    ("Refactoriser sans peur", 4, None, None, "both"),
    ("Pâte à pizza : le secret de l'hydratation", 5, None, 0.8, "audio"),
    ("Le pain au levain en cinq étapes", 0, None, None, "video"),
    ("La chute de l'Empire romain d'Occident", 3, "watched", None, "video"),
    ("Une brève histoire du calendrier", 0, None, 0.1, "video"),
    ("Optimiser une requête SQL lente", 2, None, None, "video"),
    ("Cuisson basse température : mythes et réalités", 0, "hidden", None, "audio"),
    ("Comment on lisait les cartes au Moyen Âge", 0, None, None, "metadata"),
    ("Git", 1, None, 0.5, "video"),
    (
        "Écrire un interpréteur Python de A à Z en un après-midi, sans bibliothèque, "
        "avec des tests et une démonstration complète",
        4,
        None,
        0.6,
        "both",
    ),
    ("Ratatouille", 0, None, None, "both"),
    ("Les Carolingiens : Charlemagne, Louis le Pieux et le partage de Verdun (843)", 5, None, None, "audio"),
    ("Pourquoi votre application est lente (et comment le mesurer)", 0, None, 0.85, "video"),
    ("Tarte Tatin ratée, tarte Tatin réussie : la comparaison", 3, "watched", None, "video"),
    ("Les ponts romains encore debout aujourd'hui", 0, None, None, "metadata"),
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
    played = []
    for index, (title, rating, list_state, played_share, files) in enumerate(DEMO_VIDEOS):
        channel = channels[index % len(channels)]
        yt_video_id = f"demo{index:07d}"
        folder_path = f"/tmp/media/{channel.name}/{yt_video_id}"
        video = Video(
            channel_id=channel.id,
            yt_video_id=yt_video_id,
            title=title,
            url=f"https://www.youtube.com/watch?v={yt_video_id}",
            folder_path=folder_path,
            # Exploration's default filter keeps fiches holding a video or an audio file.
            video_path=f"{folder_path}/video.mp4" if files in ("video", "both") else None,
            audio_path=f"{folder_path}/audio.m4a" if files in ("audio", "both") else None,
            metadata_path=f"{folder_path}/metadata.json",
            media_type="metadata" if files == "metadata" else ("audio" if files == "audio" else "video"),
            published_at=now - timedelta(days=index * 3 + 1),
            downloaded_at=now - timedelta(days=index),
            duration_seconds=300 + index * 217,
            view_count=1_000 * (index + 1),
            is_new=index < 3,
            rating=rating,
            list_state=list_state,
        )
        db.add(video)
        if played_share is not None:
            played.append((video, played_share))
    db.commit()
    # The cards' progress bar reads the latest playback report, as the players send it.
    for video, played_share in played:
        duration = float(video.duration_seconds)
        record_playback_activity(
            db, video, "video", duration * played_share, duration, duration * played_share
        )
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
