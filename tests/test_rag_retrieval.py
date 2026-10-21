from back.services.rag import retrieval as rag_retrieval
from back.services.rag.embeddings import EmbeddingError
from back.services.rag.retrieval import RetrievedChunk


def chunk(video_id, content="- fait"):
    return RetrievedChunk(
        video_id=video_id,
        video_title=f"Vidéo {video_id}",
        section="Faits",
        content=content,
        channel_name="Chaîne",
    )


def test_rerank_chunks_orders_by_score_and_drops_those_under_the_floor(monkeypatch):
    chunks = [chunk(1), chunk(2), chunk(3)]
    seen = []

    def fake_rerank(question, documents):
        seen.append(documents)
        return [(0, 0.05), (1, 0.8), (2, 0.4)]

    monkeypatch.setattr(rag_retrieval, "rerank", fake_rerank)

    kept = rag_retrieval.rerank_chunks("question", chunks)

    assert [c.video_id for c in kept] == [2, 3]
    # The reranker reads the same contextualized text as the embeddings.
    assert seen[0][0] == "Vidéo 1 — Chaîne — Faits\n- fait"


def test_rerank_chunks_keeps_the_vector_order_when_the_api_fails(monkeypatch):
    chunks = [chunk(1), chunk(2)]

    def failing(question, documents):
        raise EmbeddingError("API down")

    monkeypatch.setattr(rag_retrieval, "rerank", failing)

    assert rag_retrieval.rerank_chunks("question", chunks) == chunks


def test_rerank_chunks_without_candidates_does_not_call_the_api(monkeypatch):
    def failing(question, documents):
        raise AssertionError("must not be called")

    monkeypatch.setattr(rag_retrieval, "rerank", failing)

    assert rag_retrieval.rerank_chunks("question", []) == []
