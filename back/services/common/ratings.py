"""Star rating (0 to 5) of a channel or a fiche, shared by the HTML pages and `/api`."""

from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.video import Video

# Same bounds as the `ck_*_rating_range` constraints of both tables.
MIN_RATING = 0
MAX_RATING = 5


class InvalidRatingError(ValueError):
    pass


def check_rating(rating: int) -> None:
    if not MIN_RATING <= rating <= MAX_RATING:
        raise InvalidRatingError(f"La note doit être comprise entre {MIN_RATING} et {MAX_RATING}.")


def set_rating(db: Session, item: Channel | Video, rating: int) -> None:
    check_rating(rating)
    item.rating = rating
    db.commit()
