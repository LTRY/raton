from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back.db.session import Base


class LibraryChatConversation(Base):
    """One discussion of the library chat: its messages are `library_chat_messages` rows.

    `title` is the first question, shortened (back/services/library_chat/history.py).
    `updated_at` moves with each answer, so the list shows the latest discussion first.
    """

    __tablename__ = "library_chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    messages = relationship(
        "LibraryChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="LibraryChatMessage.id",
    )
