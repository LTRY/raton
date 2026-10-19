from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LibraryChatMessage(Base):
    """One message in the single continuous cross-video ("whole library") chat.

    Unlike per-video chat (a transcript.chat.json file next to each video),
    this scope has no natural per-video file to live beside, so it's a DB
    table instead. `sources` and `channel_sources` are comma-separated lists of
    the video ids and channel ids an assistant answer cited (see
    app/services/rag/library_chat_tools.py), used to render the chips under it;
    always null on user messages.
    """

    __tablename__ = "library_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
