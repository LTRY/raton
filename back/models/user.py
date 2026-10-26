"""The users of Raton and what each one keeps for themselves.

The fiches, their files, transcripts and generated notes are shared; a user's own view of them
(Vu/Indésirée, stars, comment, Nouveautés, cloches...) lives in the per-user rows below. A missing
row means the defaults (see docs/spec/05-modele-de-donnees.md, « Utilisateurs »).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from back.db.session import Base

USER_NAME_LENGTH = 40


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(USER_NAME_LENGTH), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserVideo(Base):
    """One user's state on one fiche."""

    __tablename__ = "user_videos"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_user_videos_rating_range"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # NULL = follows the automatic detection; else "watched", "unwatched" or "hidden".
    list_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # First time this user's playback reached 90%. `videos.watched_at` is the first time for
    # anyone, which starts the purge countdown of the shared files.
    watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserChannel(Base):
    """One user's state on one channel: stars and the two cloches."""

    __tablename__ = "user_channels"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_user_channels_rating_range"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auto_metadata_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_shorts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UserSetting(Base):
    """Key-value settings of one user (saved views, screen-time limits, Raton's visits)."""

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
