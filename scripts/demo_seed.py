"""Demo data for throwaway instances (the screenshots of scripts/screenshot.sh).

Run as `python -m scripts.demo_seed` against an empty sqlite database: it
creates the tables and a handful of channels and videos, then does nothing on
the following runs. No media files exist behind these rows, so players have
nothing to play, but every list and detail page has something to show. A few fiches get a
transcript (`DEMO_TRANSCRIPTS`), so the LLM features (notes, quiz, discussion) have something
to work on when the instance has an API key. The stars, cloches, Vu and playback are the first
user's; a second user (`DEMO_OTHER_USER`) starts with nothing, to show the switch of user.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.core.config import get_settings
from back.db.base import *  # noqa: F403  (registers every model on Base.metadata)
from back.db.session import Base, SessionLocal, engine
from back.models.channel import Channel
from back.models.user import User, UserChannel, UserVideo
from back.models.video import TranscriptStatus, Video
from back.services.common.users import default_user
from back.services.videos.playback import record_playback_activity
from scripts.demo_transcripts import DEMO_TRANSCRIPTS

DEMO_OTHER_USER = "Invité"

# One long name, so the channel page header is shown wrapping onto two lines.
DEMO_CHANNELS = [
    ("Atelier du code", "UCdemo000000000000000001", True),
    ("Carnets de cuisine", "UCdemo000000000000000002", False),
    ("Chroniques d'histoire de la Méditerranée antique", "UCdemo000000000000000003", True),
]

# (title, rating, list_state, share of the video already played): enough variety for every
# shape of card — one- and long multi-line titles, stars, Vu/Indesiree, a progress bar.
DEMO_VIDEOS = [
    ("Introduction aux tests automatisés", 0, None, 0.35),
    ("Refactoriser sans peur", 4, None, None),
    ("Pâte à pizza : le secret de l'hydratation", 5, None, 0.8),
    ("Le pain au levain en cinq étapes", 0, None, None),
    ("La chute de l'Empire romain d'Occident", 3, "watched", None),
    ("Une brève histoire du calendrier", 0, None, 0.1),
    ("Optimiser une requête SQL lente", 2, None, None),
    ("Cuisson basse température : mythes et réalités", 0, "hidden", None),
    ("Comment on lisait les cartes au Moyen Âge", 0, None, None),
    ("Git", 1, None, 0.5),
    (
        "Écrire un interpréteur Python de A à Z en un après-midi, sans bibliothèque, "
        "avec des tests et une démonstration complète",
        4,
        None,
        0.6,
    ),
    ("Ratatouille", 0, None, None),
    ("Les Carolingiens : Charlemagne, Louis le Pieux et le partage de Verdun (843)", 5, None, None),
    ("Pourquoi votre application est lente (et comment le mesurer)", 0, None, 0.85),
    ("Tarte Tatin ratée, tarte Tatin réussie : la comparaison", 3, "watched", None),
    ("Les ponts romains encore debout aujourd'hui", 0, None, None),
]


def seed_demo(db: Session, media_root: Path) -> bool:
    """Insert the demo rows, and the transcripts under `media_root`; return False when the
    database already has channels."""
    if db.scalar(select(Channel.id).limit(1)) is not None:
        return False
    now = datetime.now(UTC)
    user_id = default_user(db).id
    db.add(User(name=DEMO_OTHER_USER))
    channels = []
    for name, yt_channel_id, bell in DEMO_CHANNELS:
        channel = Channel(
            url=f"https://www.youtube.com/channel/{yt_channel_id}",
            name=name,
            yt_channel_id=yt_channel_id,
        )
        db.add(channel)
        db.flush()
        db.add(
            UserChannel(
                user_id=user_id,
                channel_id=channel.id,
                rating=3,
                auto_metadata_enabled=bell,
                auto_shorts_enabled=False,
            )
        )
        channels.append(channel)
    db.flush()
    played = []
    for index, (title, rating, list_state, played_share) in enumerate(DEMO_VIDEOS):
        channel = channels[index % len(channels)]
        yt_video_id = f"demo{index:07d}"
        video = Video(
            channel_id=channel.id,
            yt_video_id=yt_video_id,
            title=title,
            url=f"https://www.youtube.com/watch?v={yt_video_id}",
            folder_path=str(media_root / channel.name / yt_video_id),
            published_at=now - timedelta(days=index * 3 + 1),
            downloaded_at=now - timedelta(days=index),
            duration_seconds=300 + index * 217,
            view_count=1_000 * (index + 1),
        )
        transcript = DEMO_TRANSCRIPTS.get(title)
        if transcript:
            path = Path(video.folder_path) / "transcript.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(transcript, encoding="utf-8")
            video.transcript_path = str(path)
            video.transcript_status = TranscriptStatus.downloaded
        db.add(video)
        db.flush()
        db.add(
            UserVideo(
                user_id=user_id,
                video_id=video.id,
                rating=rating,
                list_state=list_state,
                is_new=index < 3,
            )
        )
        if played_share is not None:
            played.append((video, played_share))
    db.commit()
    # The cards' progress bar reads the latest playback report, as the players send it.
    for video, played_share in played:
        duration = float(video.duration_seconds)
        record_playback_activity(
            db, user_id, video, "video", duration * played_share, duration, duration * played_share
        )
    return True


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo(db, get_settings().media_root)
    finally:
        db.close()


if __name__ == "__main__":
    main()
