"""Per-user state for tests: the fiches and channels as one user (the default one unless told)
sees them, now that stars, Vu, Nouveau and cloches live in `user_videos` / `user_channels`."""

from back.models.user import User, UserChannel, UserVideo
from back.services.common.user_state import channel_state, video_state
from back.services.common.users import default_user


def user_id(db) -> int:
    """The default user's id (created on first use, like a request naming no user does)."""
    return default_user(db).id


def add_user(db, name: str) -> User:
    """A second user; the default one is created first, so it stays the oldest."""
    default_user(db)
    user = User(name=name)
    db.add(user)
    db.commit()
    return user


def set_video_state(db, video, user: int | None = None, **fields) -> UserVideo:
    """Set `rating`, `list_state`, `comment`, `is_new` or `watched_at` of `video` for a user."""
    if video.id is None:
        db.flush()
    state = video_state(db, user if user is not None else user_id(db), video.id)
    for name, value in fields.items():
        setattr(state, name, value)
    db.commit()
    return state


def set_channel_state(db, channel, user: int | None = None, **fields) -> UserChannel:
    """Set `rating`, `auto_metadata_enabled` or `auto_shorts_enabled` of `channel` for a user."""
    if channel.id is None:
        db.flush()
    state = channel_state(db, user if user is not None else user_id(db), channel.id)
    for name, value in fields.items():
        setattr(state, name, value)
    db.commit()
    return state


def stored_video_state(db, video, user: int | None = None) -> UserVideo | None:
    db.expire_all()
    return db.get(UserVideo, (user if user is not None else user_id(db), video.id))


def stored_channel_state(db, channel, user: int | None = None) -> UserChannel | None:
    db.expire_all()
    return db.get(UserChannel, (user if user is not None else user_id(db), channel.id))


def follow(db, *channels, videos: bool = True, shorts: bool = False, user: int | None = None):
    """Turn the default user's (or `user`'s) cloches of these channels on."""
    for channel in channels:
        set_channel_state(
            db, channel, user, auto_metadata_enabled=videos, auto_shorts_enabled=shorts
        )


# The fields of a test's `Video(...)` / `Channel(...)` that now belong to a user.
VIDEO_STATE_FIELDS = ("rating", "list_state", "comment", "is_new")
CHANNEL_STATE_FIELDS = ("rating", "auto_metadata_enabled", "auto_shorts_enabled")


def pop_state(fields: dict, names) -> dict:
    """Take the per-user fields out of a row's keyword arguments."""
    return {name: fields.pop(name) for name in names if name in fields}


# The id the default user gets in a fresh test DB (`default_user` creates it on first use).
FIRST_USER_ID = 1


def mine(**fields) -> list[UserVideo]:
    """`Video(user_states=mine(rating=4))`: the default user's state, saved with the fiche."""
    return [UserVideo(user_id=FIRST_USER_ID, **{**_VIDEO_DEFAULTS, **fields})]


def my_channel(**fields) -> list[UserChannel]:
    """`Channel(user_states=my_channel(rating=5))`: the default user's stars and cloches."""
    return [UserChannel(user_id=FIRST_USER_ID, **{**_CHANNEL_DEFAULTS, **fields})]


_VIDEO_DEFAULTS = {"rating": 0, "list_state": None, "comment": None, "is_new": False}
_CHANNEL_DEFAULTS = {"rating": 0, "auto_metadata_enabled": False, "auto_shorts_enabled": False}
