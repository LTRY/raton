"""The library chat's discussions (`library_chat_conversations`) and their messages; each
discussion belongs to one user, and only they can read, continue or delete it."""

from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.library_chat_conversation import LibraryChatConversation
from back.models.library_chat_message import LibraryChatMessage
from back.models.video import Video
from back.services.library_chat.tools import parse_source_ids

TITLE_LENGTH = 80
# The discussions list shows the latest ones; older ones stay in the DB.
LISTED_CONVERSATIONS = 50


class ConversationNotFoundError(ValueError):
    def __init__(self) -> None:
        super().__init__("Discussion introuvable.")


def _join_source_ids(ids: list[int]) -> str | None:
    return ",".join(str(item_id) for item_id in ids) or None


def conversation_title(question: str) -> str:
    """The first question on one line, cut to `TITLE_LENGTH` characters."""
    title = " ".join(question.split()) or "Discussion"
    if len(title) > TITLE_LENGTH:
        title = title[: TITLE_LENGTH - 1].rstrip() + "…"
    return title


def get_conversation(db: Session, user_id: int, conversation_id: int) -> LibraryChatConversation:
    conversation = db.get(LibraryChatConversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFoundError()
    return conversation


def start_conversation(db: Session, user_id: int, question: str) -> LibraryChatConversation:
    """A new discussion of the user, named after its first question; the caller commits."""
    conversation = LibraryChatConversation(user_id=user_id, title=conversation_title(question))
    db.add(conversation)
    db.flush()
    return conversation


def _has_messages():
    return exists().where(LibraryChatMessage.conversation_id == LibraryChatConversation.id)


def list_conversations(db: Session, user_id: int) -> list[LibraryChatConversation]:
    """The user's latest discussions, most recently answered first. A discussion whose first
    question never got an answer has no message and is not listed."""
    return list(
        db.scalars(
            select(LibraryChatConversation)
            .where(LibraryChatConversation.user_id == user_id, _has_messages())
            .order_by(LibraryChatConversation.updated_at.desc(), LibraryChatConversation.id.desc())
            .limit(LISTED_CONVERSATIONS)
        )
    )


def chat_rows(db: Session, conversation_id: int | None) -> list[LibraryChatMessage]:
    if conversation_id is None:
        return []
    return list(
        db.scalars(
            select(LibraryChatMessage)
            .where(LibraryChatMessage.conversation_id == conversation_id)
            .order_by(LibraryChatMessage.id)
        )
    )


def chat_history(db: Session, conversation_id: int | None) -> list[dict[str, str]]:
    """The discussion as the model reads it: role and text of each message."""
    return [{"role": row.role, "content": row.content} for row in chat_rows(db, conversation_id)]


def chat_messages(db: Session, conversation_id: int | None) -> list[dict]:
    """The discussion as the page shows it, each answer with the channels and fiches it cites."""
    rows = chat_rows(db, conversation_id)
    video_ids = {video_id for row in rows for video_id in parse_source_ids(row.sources)}
    channel_ids = {
        channel_id for row in rows for channel_id in parse_source_ids(row.channel_sources)
    }
    video_titles = (
        dict(db.execute(select(Video.id, Video.title).where(Video.id.in_(video_ids))).all())
        if video_ids
        else {}
    )
    channel_names = (
        dict(db.execute(select(Channel.id, Channel.name).where(Channel.id.in_(channel_ids))).all())
        if channel_ids
        else {}
    )
    return [
        {
            "role": row.role,
            "content": row.content,
            # Channels and videos deleted since the answer was given are
            # silently dropped rather than shown as broken links.
            "channels": [
                {"channel_id": channel_id, "name": channel_names[channel_id]}
                for channel_id in parse_source_ids(row.channel_sources)
                if channel_id in channel_names
            ],
            "citations": [
                {"video_id": video_id, "title": video_titles[video_id]}
                for video_id in parse_source_ids(row.sources)
                if video_id in video_titles
            ],
        }
        for row in rows
    ]


def total_video_count(db: Session) -> int:
    return db.scalar(select(func.count(Video.id))) or 0


def add_chat_exchange(
    db: Session,
    conversation: LibraryChatConversation,
    question: str,
    answer: str,
    video_ids: list[int],
    channel_ids: list[int],
) -> None:
    """Append a question and its answer to the discussion; the caller commits."""
    db.add(LibraryChatMessage(conversation_id=conversation.id, role="user", content=question))
    db.add(
        LibraryChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources=_join_source_ids(video_ids),
            channel_sources=_join_source_ids(channel_ids),
        )
    )
    conversation.updated_at = datetime.now(UTC)


def delete_conversation(db: Session, user_id: int, conversation_id: int) -> None:
    db.delete(get_conversation(db, user_id, conversation_id))
    db.commit()
