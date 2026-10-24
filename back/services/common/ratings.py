"""Star rating (0 to 5) a user gives a channel or a fiche, shared by the HTML pages and `/api`."""

from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.video import Video
from back.services.common.user_state import channel_state, video_state

# Same bounds as the `ck_user_*_rating_range` constraints of both tables.
MIN_RATING = 0
MAX_RATING = 5


class InvalidRatingError(ValueError):
    pass


def check_rating(rating: int) -> None:
    if not MIN_RATING <= rating <= MAX_RATING:
        raise InvalidRatingError(f"La note doit être comprise entre {MIN_RATING} et {MAX_RATING}.")


def set_rating(db: Session, user_id: int, item: Channel | Video, rating: int) -> None:
    check_rating(rating)
    if isinstance(item, Channel):
        channel_state(db, user_id, item.id).rating = rating
    else:
        video_state(db, user_id, item.id).rating = rating
    db.commit()
