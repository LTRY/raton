"""Embeddings and reranking for cross-video RAG search over structured notes, from the Voyage AI API.

Voyage is the embedding provider Anthropic recommends (Anthropic has no embedding
model of its own). Nothing runs locally: the first version used a CPU
sentence-transformers model, whose load time made the first notes search of
every restart slow. The vectors of the notes already indexed come from one
model: changing `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` or the text given to
`embed_texts` requires re-embedding every chunk (see docs/spec/19).
"""

import logging

import httpx

from app.core.config import get_settings
from app.core.logging import log_external

logger = logging.getLogger(__name__)

VOYAGE_EMBEDDINGS_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
# Must match the `vector(N)` column of video_note_chunks. voyage-3.5 accepts
# 256/512/1024/2048 through `output_dimension`.
EMBEDDING_DIMENSIONS = 1024
# The API refuses more inputs than this in one embeddings request.
MAX_INPUTS_PER_REQUEST = 128
REQUEST_TIMEOUT_SECONDS = 30.0


class EmbeddingError(RuntimeError):
    """The Voyage API could not be used; the message is meant for the user."""


def contextualized_text(
    video_title: str, channel_name: str | None, section: str, content: str
) -> str:
    """What is embedded and reranked for a chunk: its content with the video it comes from.

    A bare bullet list ("- La dichotomie du contrôle") says nothing about its
    source; the header lets the vector and the reranker tell which video and
    which kind of notes it is. The stored `content` stays the bare text.
    """
    source = " — ".join(part for part in (video_title, channel_name, section) if part)
    return f"{source}\n{content}"


def _post(url: str, body: dict) -> dict:
    settings = get_settings()
    if not settings.voyage_api_key:
        raise EmbeddingError(
            "VOYAGE_API_KEY n'est pas configurée : la recherche dans les notes est indisponible."
        )
    try:
        with log_external(logger, "voyage", url.rsplit("/", 1)[-1]):
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise EmbeddingError(
            f"Voyage a refusé la requête (HTTP {exc.response.status_code})."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingError(
            f"Voyage est injoignable ou a répondu de façon inattendue : {exc}"
        ) from exc


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_INPUTS_PER_REQUEST):
        body = {
            "input": texts[start : start + MAX_INPUTS_PER_REQUEST],
            "model": get_settings().embedding_model,
            "input_type": input_type,
            "output_dimension": EMBEDDING_DIMENSIONS,
        }
        try:
            data = sorted(
                _post(VOYAGE_EMBEDDINGS_URL, body)["data"], key=lambda item: item["index"]
            )
            vectors.extend(item["embedding"] for item in data)
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(f"Voyage a répondu de façon inattendue : {exc}") from exc
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed note sections to store: Voyage prepends a document prompt for this input type."""
    if not texts:
        return []
    return _embed(texts, "document")


def embed_text(text: str) -> list[float]:
    """Embed a search question: the `query` input type is what the stored `document` vectors are matched with."""
    return _embed([text], "query")[0]


def rerank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Score every document against the query with a cross-encoder: (index in `documents`, relevance score).

    Unlike the embeddings, the model reads the query and the document together,
    so it is far more precise — and cannot be precomputed, which is why it only
    runs on the few candidates the vector search kept.
    """
    if not documents:
        return []
    body = {"query": query, "documents": documents, "model": get_settings().rerank_model}
    try:
        return [
            (item["index"], float(item["relevance_score"]))
            for item in _post(VOYAGE_RERANK_URL, body)["data"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise EmbeddingError(f"Voyage a répondu de façon inattendue : {exc}") from exc
