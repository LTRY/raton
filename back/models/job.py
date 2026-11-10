from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back.db.session import Base


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (
        # A user's `played` rows, newest first: the Historique, screen time, Raton's visits.
        Index("ix_download_jobs_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Whose activity a `played` or `prompt` line is (history, positions, screen time); NULL on
    # the other lines, which are the library's, and on lines older than the users.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    channel = relationship("Channel", back_populates="jobs")
    video = relationship("Video", back_populates="jobs")
