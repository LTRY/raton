from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.services.rag.embeddings import EMBEDDING_DIMENSIONS


class VideoNoteChunk(Base):
    """One embedded section of a video's structured notes, for cross-video RAG search.

    Populated by app/services/rag/indexing.py whenever notes are (re)generated in
    the Markdown-sectioned format produced by build_notes_prompt; a video only
    becomes searchable from the cross-video chat once it has at least one row
    here. Rows are replaced wholesale on regeneration (see
    docs/spec/09-transcript-et-discussion-llm.md).
    """

    __tablename__ = "video_note_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    video = relationship("Video")
