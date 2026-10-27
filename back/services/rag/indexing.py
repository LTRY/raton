"""Chunk + embed a video's structured notes into VideoNoteChunk rows.

The chunking is local, the embedding is a call to the Voyage API
(back/services/rag/embeddings.py). It is not an LLM completion, so it runs right
after notes are applied (`run_notes_indexing_job` in back/services/jobs/llm_jobs.py) rather
than going through the LlmJob queued/running/done lifecycle used for text generation.
"""

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from back.core.config import get_settings, local_media_path
from back.models.channel import Channel
from back.models.video import Video
from back.models.video_note_chunk import VideoNoteChunk
from back.services.llm.prompts import split_notes_sections
from back.services.rag.embeddings import EmbeddingError, contextualized_text, embed_texts
from back.services.videos.documents import NOTES_FILE, SHORT_SUMMARY_FILE

logger = logging.getLogger(__name__)

SUMMARY_SECTION_NAME = "Résumé"


def read_summary_short(transcript_path: str) -> str | None:
    """The short résumé written next to a video's transcript, if there is one."""
    try:
        text = (
            local_media_path(transcript_path)
            .with_name(SHORT_SUMMARY_FILE)
            .read_text(encoding="utf-8")
        )
    except OSError:
        return None
    return text.strip() or None


def in_indexed_channel():
    """Filter: the video has no channel, or its channel is indexed by the RAG."""
    return or_(
        Video.channel_id.is_(None),
        Video.channel_id.not_in(select(Channel.id).where(Channel.rag_indexed.is_(False))),
    )


def index_video_notes(
    db: Session, video_id: int, notes_text: str, summary_short: str | None = None
) -> None:
    """Replace a video's chunks: one per notes section, plus one for its short résumé when it has one.

    The résumé gives the gist of the video, which the notes (atomic facts) do not. Commits the
    caller's session. A video of a channel that is not indexed by the RAG is left out.
    """
    video = db.get(Video, video_id)
    if video is None or (video.channel is not None and not video.channel.rag_indexed):
        return
    channel_name = video.channel.name if video.channel is not None else None
    sections = split_notes_sections(notes_text)
    if summary_short and summary_short.strip():
        sections.append((SUMMARY_SECTION_NAME, summary_short.strip()))
    # Embedded before the old chunks are deleted: an API failure keeps the
    # previous index instead of leaving the video unsearchable.
    embeddings = (
        embed_texts(
            [
                contextualized_text(video.title, channel_name, name, content)
                for name, content in sections
            ]
        )
        if sections
        else []
    )
    db.query(VideoNoteChunk).filter(VideoNoteChunk.video_id == video_id).delete()
    for (section, content), embedding in zip(sections, embeddings, strict=True):
        db.add(
            VideoNoteChunk(video_id=video_id, section=section, content=content, embedding=embedding)
        )
    db.commit()


def backfill_note_chunks(db: Session) -> int:
    """Index the videos that have a notes file but no chunk; returns how many were indexed.

    Needed once after the move to Voyage embeddings (the migration drops the
    local model's vectors), and afterwards for notes written while the API key
    was missing. A no-op without a key. Stops at the first API failure: the
    next startup retries.
    """
    if not get_settings().voyage_api_key:
        return 0
    indexed_ids = select(VideoNoteChunk.video_id).distinct()
    candidates = db.execute(
        select(Video.id, Video.transcript_path).where(
            Video.transcript_path.is_not(None),
            Video.id.not_in(indexed_ids),
            in_indexed_channel(),
        )
    ).all()
    indexed = 0
    for video_id, transcript_path in candidates:
        notes_path = local_media_path(transcript_path).with_name(NOTES_FILE)
        try:
            notes_text = notes_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not split_notes_sections(notes_text):
            continue
        try:
            index_video_notes(db, video_id, notes_text, read_summary_short(transcript_path))
        except EmbeddingError as exc:
            logger.warning("Indexation des notes interrompue : %s", exc)
            break
        indexed += 1
    return indexed


def backfill_summary_chunks(db: Session) -> int:
    """Re-index the videos that have notes chunks and a short résumé file but no résumé chunk.

    Covers the videos generated before the résumé was indexed; no LLM call is involved, only the
    embedding. Stops at the first API failure, like `backfill_note_chunks`.
    """
    if not get_settings().voyage_api_key:
        return 0
    with_summary_chunk = select(VideoNoteChunk.video_id).where(
        VideoNoteChunk.section == SUMMARY_SECTION_NAME
    )
    with_notes_chunks = select(VideoNoteChunk.video_id).distinct()
    candidates = db.execute(
        select(Video.id, Video.transcript_path).where(
            Video.transcript_path.is_not(None),
            Video.id.in_(with_notes_chunks),
            Video.id.not_in(with_summary_chunk),
        )
    ).all()
    indexed = 0
    for video_id, transcript_path in candidates:
        summary = read_summary_short(transcript_path)
        if summary is None:
            continue
        try:
            notes_text = (
                local_media_path(transcript_path).with_name(NOTES_FILE).read_text(encoding="utf-8")
            )
        except OSError:
            continue
        try:
            index_video_notes(db, video_id, notes_text, summary)
        except EmbeddingError as exc:
            logger.warning("Indexation des résumés interrompue : %s", exc)
            break
        indexed += 1
    return indexed
