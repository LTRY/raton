"""The library chat's conversation, kept in `library_chat_messages`."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.library_chat_message import LibraryChatMessage
from app.models.video import Video
from app.services.library_chat.tools import parse_source_ids


def _join_source_ids(ids: list[int]) -> str | None:
    return ",".join(str(item_id) for item_id in ids) or None


def chat_rows(db: Session) -> list[LibraryChatMessage]:
    return list(db.scalars(select(LibraryChatMessage).order_by(LibraryChatMessage.id)))


def chat_history(db: Session) -> list[dict[str, str]]:
    """The conversation as the model reads it: role and text of each message."""
    return [{"role": row.role, "content": row.content} for row in chat_rows(db)]


def chat_messages(db: Session) -> list[dict]:
    """The conversation as the page shows it, each answer with the channels and fiches it cites."""
    rows = chat_rows(db)
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
    db: Session, question: str, answer: str, video_ids: list[int], channel_ids: list[int]
) -> None:
    """Append a question and its answer; the caller commits."""
    db.add(LibraryChatMessage(role="user", content=question))
    db.add(
        LibraryChatMessage(
            role="assistant",
            content=answer,
            sources=_join_source_ids(video_ids),
            channel_sources=_join_source_ids(channel_ids),
        )
    )


def clear_chat(db: Session) -> None:
    db.query(LibraryChatMessage).delete()
    db.commit()
