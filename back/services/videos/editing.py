"""Changes a person makes to a fiche: categories (shared), and their own comment and Vu/Indésirée
state."""

from sqlalchemy.orm import Session

from back.models.user import UserVideo
from back.models.video import Video
from back.services.common.categories import serialized_category_labels
from back.services.common.settings import add_video_category_labels
from back.services.common.user_state import video_state
from back.services.videos.list_state import VIDEO_LIST_STATES


def mark_video_opened(db: Session, user_id: int, video: Video) -> None:
    """Opening a fiche takes it out of the user's Nouveautés."""
    state = db.get(UserVideo, (user_id, video.id))
    if state is not None and state.is_new:
        state.is_new = False
        db.commit()


def set_video_categories(db: Session, video: Video, labels: list[str]) -> None:
    video.category_labels = serialized_category_labels(labels)
    add_video_category_labels(db, labels)
    db.commit()


def set_video_comment(db: Session, user_id: int, video: Video, comment: str) -> None:
    video_state(db, user_id, video.id).comment = comment.strip() or None
    db.commit()


def set_video_list_state(db: Session, user_id: int, video: Video, state: str) -> None:
    """Force the Vu/Indésirée state; "clear" goes back to the state deduced from playback."""
    if state != "clear" and state not in VIDEO_LIST_STATES:
        raise ValueError("État de liste inconnu.")
    video_state(db, user_id, video.id).list_state = None if state == "clear" else state
    db.commit()
