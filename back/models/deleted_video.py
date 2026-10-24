from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from back.db.session import Base


class DeletedVideo(Base):
    """YouTube id of a fiche the person deleted, so the scan does not bring it back.

    Only the scan reads it (back/services/ingest/identity.py:video_known); an import the person
    asks for recreates the fiche anyway.
    """

    __tablename__ = "deleted_videos"

    yt_video_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
