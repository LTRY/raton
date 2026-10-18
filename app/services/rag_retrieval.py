"""Cross-video RAG retrieval: given a question, find the most relevant notes chunks.

Read-side counterpart to app/services/rag_indexing.py (which writes/embeds
chunks). Exposed to the library-wide chat as one of its tools
(app/services/library_chat_tools.py) to ground answers in the user's own video
notes instead of the model's general knowledge.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import Video
from app.models.video_note_chunk import VideoNoteChunk
from app.services.embeddings import EmbeddingError, contextualized_text, embed_text, rerank

logger = logging.getLogger(__name__)

# Small fixed numbers, not an adaptive similarity threshold — simple and
# predictable in size/cost, appropriate at a personal-library scale.
TOP_K_CHUNKS = 8
# A video has several note sections, so without a cap the one closest video
# fills every slot and hides the others.
MAX_CHUNKS_PER_VIDEO = 2
# How many nearest chunks the vector search hands to the reranker. The reranker
# cannot bring back a chunk this cut left out, so it is the recall ceiling.
CANDIDATE_CHUNKS = 50
# Reranker score under which a chunk is dropped rather than shown to the model:
# with no floor, the top chunks were returned even when nothing matched, which
# pushed the model to build an answer from unrelated notes. Not calibrated on
# real data yet: the scores are logged by `rerank_chunks` so it can be tuned
# (docs/spec/19).
MIN_RELEVANCE_SCORE = 0.2


@dataclass
class RetrievedChunk:
    video_id: int
    video_title: str
    section: str
    content: str
    channel_id: int | None = None
    channel_name: str | None = None


def diversify_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep the closest chunks, at most MAX_CHUNKS_PER_VIDEO from any one video.

    `chunks` must already be ordered from closest to farthest.
    """
    kept: list[RetrievedChunk] = []
    per_video: dict[int, int] = {}
    for chunk in chunks:
        if per_video.get(chunk.video_id, 0) >= MAX_CHUNKS_PER_VIDEO:
            continue
        per_video[chunk.video_id] = per_video.get(chunk.video_id, 0) + 1
        kept.append(chunk)
        if len(kept) == TOP_K_CHUNKS:
            break
    return kept


def rerank_chunks(question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reorder the vector search's candidates by reranker score and drop the irrelevant ones.

    The reranker only sharpens the result: if the API fails the candidates are
    returned as they came (closest first, no floor) instead of failing the search.
    """
    if not chunks:
        return []
    documents = [
        contextualized_text(chunk.video_title, chunk.channel_name, chunk.section, chunk.content)
        for chunk in chunks
    ]
    try:
        scored = sorted(rerank(question, documents), key=lambda item: item[1], reverse=True)
    except EmbeddingError as exc:
        logger.warning("Reranking indisponible, ordre vectoriel conservé : %s", exc)
        return chunks
    logger.info(
        "reranking de %d extrait(s) pour %r : meilleurs scores %s, %d au-dessus du seuil %.2f",
        len(chunks),
        question,
        [round(score, 2) for _, score in scored[:8]],
        sum(1 for _, score in scored if score >= MIN_RELEVANCE_SCORE),
        MIN_RELEVANCE_SCORE,
    )
    return [chunks[index] for index, score in scored if score >= MIN_RELEVANCE_SCORE]


def retrieve_relevant_chunks(db: Session, question: str) -> list[RetrievedChunk]:
    query_embedding = embed_text(question)
    rows = db.execute(
        select(VideoNoteChunk, Video.title, Channel.id, Channel.name)
        .join(Video, Video.id == VideoNoteChunk.video_id)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .order_by(VideoNoteChunk.embedding.cosine_distance(query_embedding))
        .limit(CANDIDATE_CHUNKS)
    ).all()
    candidates = [
        RetrievedChunk(
            video_id=chunk.video_id,
            video_title=title,
            section=chunk.section,
            content=chunk.content,
            channel_id=channel_id,
            channel_name=channel_name,
        )
        for chunk, title, channel_id, channel_name in rows
    ]
    return diversify_chunks(rerank_chunks(question, candidates))


def count_indexed_videos(db: Session) -> int:
    """How many distinct videos currently have at least one searchable chunk.

    Used alongside the total video count to tell the user how much of their
    library the cross-video chat can actually see (see docs/spec/09).
    """
    return db.scalar(select(func.count(func.distinct(VideoNoteChunk.video_id)))) or 0
