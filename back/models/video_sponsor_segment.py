from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back.db.session import Base


class VideoSponsorSegment(Base):
    """Un segment sponsor/selfpromo/interaction/intro/outro d'une vidéo.

    `source` ne contient que `"sponsorblock"` aujourd'hui — la détection par LLM,
    qui écrivait aussi des lignes `"llm"`, a été retirée (une ancienne migration a supprimé ces lignes). La colonne est
    conservée : relancer la récupération d'une source ne remplace que les lignes
    de cette source pour la vidéo
    (back/services/youtube/sponsor_segments.py:replace_video_sponsor_segments), donc une
    seconde source pourrait être réintroduite sans migration.
    """

    __tablename__ = "video_sponsor_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    video = relationship("Video", back_populates="sponsor_segments")
