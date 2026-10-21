"""Changes a person makes to a fiche: categories, comment, title, Vu/Écartée state."""

from sqlalchemy.orm import Session

from back.models.video import Video
from back.services.common.categories import serialized_category_labels
from back.services.common.settings import add_video_category_labels
from back.services.videos.list_state import VIDEO_LIST_STATES

# Mark a title as chosen among the AI suggestions (✨) or typed by hand (✏️).


def mark_video_opened(db: Session, video: Video) -> None:
    """Opening a fiche takes it out of the Nouveautés."""
    if video.is_new:
        video.is_new = False
        db.commit()


def set_video_categories(db: Session, video: Video, labels: list[str]) -> None:
    video.category_labels = serialized_category_labels(labels)
    add_video_category_labels(db, labels)
    db.commit()


def set_video_comment(db: Session, video: Video, comment: str) -> None:
    video.comment = comment.strip() or None
    db.commit()


def set_video_list_state(db: Session, video: Video, state: str) -> None:
    """Force the Vu/Écartée state; "clear" goes back to the state deduced from playback."""
    if state != "clear" and state not in VIDEO_LIST_STATES:
        raise ValueError("État de liste inconnu.")
    video.list_state = None if state == "clear" else state
    db.commit()
