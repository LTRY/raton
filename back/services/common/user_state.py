"""Each user's own state on the shared fiches and channels (`user_videos`, `user_channels`).

A fiche or channel a user never touched has no row: reads get a detached row holding the
defaults, writes create the row. SQL that filters or sorts on this state outer-joins the row of
one user (`video_state_join`, `channel_state_join`) and reads its columns through `coalesce`.
"""

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.user import UserChannel, UserVideo
from back.models.video import Video


def blank_video_state(user_id: int, video_id: int) -> UserVideo:
    return UserVideo(
        user_id=user_id,
        video_id=video_id,
        rating=0,
        list_state=None,
        comment=None,
        is_new=False,
        watched_at=None,
    )


def blank_channel_state(user_id: int, channel_id: int) -> UserChannel:
    return UserChannel(
        user_id=user_id,
        channel_id=channel_id,
        rating=0,
        auto_metadata_enabled=False,
        auto_shorts_enabled=False,
    )


def video_state(db: Session, user_id: int, video_id: int) -> UserVideo:
    """The user's row for a fiche, added to the session (not committed) when missing."""
    state = db.get(UserVideo, (user_id, video_id))
    if state is None:
        state = blank_video_state(user_id, video_id)
        db.add(state)
    return state


def channel_state(db: Session, user_id: int, channel_id: int) -> UserChannel:
    """The user's row for a channel, added to the session (not committed) when missing."""
    state = db.get(UserChannel, (user_id, channel_id))
    if state is None:
        state = blank_channel_state(user_id, channel_id)
        db.add(state)
    return state


def video_states(db: Session, user_id: int, video_ids) -> dict[int, UserVideo]:
    """The user's state of each fiche of `video_ids`, in one query; defaults where no row."""
    wanted = set(video_ids)
    found = (
        {
            state.video_id: state
            for state in db.scalars(
                select(UserVideo).where(
                    UserVideo.user_id == user_id, UserVideo.video_id.in_(wanted)
                )
            )
        }
        if wanted
        else {}
    )
    return {
        video_id: found.get(video_id) or blank_video_state(user_id, video_id) for video_id in wanted
    }


def channel_states(db: Session, user_id: int, channel_ids) -> dict[int, UserChannel]:
    """The user's state of each channel of `channel_ids`, in one query; defaults where no row."""
    wanted = set(channel_ids)
    found = (
        {
            state.channel_id: state
            for state in db.scalars(
                select(UserChannel).where(
                    UserChannel.user_id == user_id, UserChannel.channel_id.in_(wanted)
                )
            )
        }
        if wanted
        else {}
    )
    return {
        channel_id: found.get(channel_id) or blank_channel_state(user_id, channel_id)
        for channel_id in wanted
    }


def video_comments(db: Session, user_id: int) -> dict[int, str]:
    """The user's comments, by fiche id (a search reads them along with the titles)."""
    return dict(
        db.execute(
            select(UserVideo.video_id, UserVideo.comment).where(
                UserVideo.user_id == user_id, UserVideo.comment.is_not(None)
            )
        ).all()
    )


def mark_new_for(db: Session, video_id: int, user_ids) -> None:
    """The fiche is Nouveau for these users (the followers of its section); does not commit."""
    for user_id in user_ids:
        video_state(db, user_id, video_id).is_new = True


def channel_followers(db: Session, channel_id: int, section: str) -> list[int]:
    """The users whose cloche of `section` ("videos" or "shorts") is on for the channel."""
    bell = (
        UserChannel.auto_shorts_enabled
        if section in {"short", "shorts"}
        else UserChannel.auto_metadata_enabled
    )
    return list(
        db.scalars(
            select(UserChannel.user_id)
            .where(UserChannel.channel_id == channel_id, bell.is_(True))
            .order_by(UserChannel.user_id)
        )
    )


def followed_channel_ids():
    """SQL: the ids of the channels with at least one cloche on, for anyone (the scan's list)."""
    return select(UserChannel.channel_id).where(
        UserChannel.auto_metadata_enabled.is_(True) | UserChannel.auto_shorts_enabled.is_(True)
    )


def video_state_join(user_id: int):
    """ON clause of the outer join of `UserVideo` (one user's rows) on `Video`."""
    return and_(UserVideo.video_id == Video.id, UserVideo.user_id == user_id)


def channel_state_join(user_id: int):
    """ON clause of the outer join of `UserChannel` (one user's rows) on `Channel`."""
    return and_(UserChannel.channel_id == Channel.id, UserChannel.user_id == user_id)


# Column reads of an outer-joined state row: a missing row reads as the defaults.
video_rating = func.coalesce(UserVideo.rating, 0)
channel_rating = func.coalesce(UserChannel.rating, 0)
video_is_new = func.coalesce(UserVideo.is_new, False)
channel_videos_bell = func.coalesce(UserChannel.auto_metadata_enabled, False)
channel_shorts_bell = func.coalesce(UserChannel.auto_shorts_enabled, False)
