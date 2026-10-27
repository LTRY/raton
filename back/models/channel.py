import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back.db.session import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    yt_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    category_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    # False keeps the channel's fiches out of the RAG index (no notes batch, no chunks); shared by
    # every user, like the channel's labels.
    rag_indexed: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list of the creator-declared tags; use `keyword_list` to read it.
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Both paths are relative to the media root, so they survive a media root move;
    # the root itself is translated with local_media_path when the files are read.
    avatar_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    banner_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # NULL means "profile never fetched": that is what the backfill job selects.
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # When the daily scan last finished this channel. It orders the scan (never scanned, then
    # least recently scanned first) so a scan cut short by a rate limit resumes where it stopped
    # instead of always starving the same channels.
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    videos = relationship("Video", back_populates="channel", cascade="all, delete-orphan")
    jobs = relationship("DownloadJob", back_populates="channel")
    # Each user's stars and cloches (back/models/user.py).
    user_states = relationship("UserChannel", cascade="all, delete-orphan")

    @property
    def keyword_list(self) -> list[str]:
        if not self.keywords:
            return []
        try:
            value = json.loads(self.keywords)
        except ValueError:
            return []
        return [str(keyword) for keyword in value if keyword] if isinstance(value, list) else []
