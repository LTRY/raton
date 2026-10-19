import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# Not StrEnum on purpose: it would change str() and format() of the members to the bare
# value, a behavior change that a lint cleanup should not slip in.
class TranscriptStatus(str, enum.Enum):  # noqa: UP042
    missing = "missing"
    downloaded = "downloaded"
    failed = "failed"


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_videos_rating_range"),
        UniqueConstraint("yt_video_id", name="uq_videos_yt_video_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=True, index=True
    )
    yt_video_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), default="video", nullable=False)
    download_source: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    imported_via_form: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # NULL = suit la détection automatique ; sinon "watched", "unwatched" ou "hidden".
    list_state: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    category_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # First time playback reached 90% (see app/services/videos/playback.py); starts the
    # retention countdown. Never overwritten, so replays don't push the deletion back.
    watched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    folder_path: Mapped[str] = mapped_column(Text, nullable=False)
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[TranscriptStatus] = mapped_column(
        Enum(TranscriptStatus, name="transcript_status"),
        default=TranscriptStatus.missing,
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Copy of `view_count` from metadata.json, so the "views" sort can run in SQL instead of reading every file.
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Copy of `duration` from metadata.json: a card shows it, and metadata.json is a ~140 KB file that
    # must not be parsed once per card.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    channel = relationship("Channel", back_populates="videos")
    jobs = relationship("DownloadJob", back_populates="video")
    sponsor_segments = relationship(
        "VideoSponsorSegment", back_populates="video", cascade="all, delete-orphan"
    )
    playlist_items = relationship(
        "PlaylistItem", back_populates="video", cascade="all, delete-orphan"
    )
