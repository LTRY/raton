import httpx
import pytest

from app.core.config import Settings
from app.services.rag import embeddings


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        return self.payload


@pytest.fixture
def voyage_key(monkeypatch):
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: Settings(VOYAGE_API_KEY="pa-test", _env_file=None)
    )


def test_embed_text_sends_a_query_request_and_returns_the_vector(monkeypatch, voyage_key):
    sent = []

    def fake_post(url, headers, json, timeout):
        sent.append((url, headers, json))
        return FakeResponse({"data": [{"index": 0, "embedding": [0.5, 0.25]}]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    assert embeddings.embed_text("reverse engineering") == [0.5, 0.25]
    url, headers, body = sent[0]
    assert url == embeddings.VOYAGE_EMBEDDINGS_URL
    assert headers == {"Authorization": "Bearer pa-test"}
    assert body == {
        "input": ["reverse engineering"],
        "model": "voyage-3.5",
        "input_type": "query",
        "output_dimension": embeddings.EMBEDDING_DIMENSIONS,
    }


def test_embed_texts_batches_and_keeps_input_order(monkeypatch, voyage_key):
    monkeypatch.setattr(embeddings, "MAX_INPUTS_PER_REQUEST", 2)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        # Out-of-order `data`: the API reports each item's index.
        data = [{"index": i, "embedding": [float(text)]} for i, text in enumerate(json["input"])]
        return FakeResponse({"data": list(reversed(data))})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    assert embeddings.embed_texts(["1", "2", "3"]) == [[1.0], [2.0], [3.0]]
    assert [call["input"] for call in calls] == [["1", "2"], ["3"]]
    assert {call["input_type"] for call in calls} == {"document"}


def test_embed_without_api_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: Settings(VOYAGE_API_KEY="", _env_file=None)
    )

    with pytest.raises(embeddings.EmbeddingError, match="VOYAGE_API_KEY"):
        embeddings.embed_text("question")


def test_embed_http_error_becomes_an_embedding_error(monkeypatch, voyage_key):
    monkeypatch.setattr(embeddings.httpx, "post", lambda *a, **k: FakeResponse({}, status_code=401))

    with pytest.raises(embeddings.EmbeddingError, match="HTTP 401"):
        embeddings.embed_text("question")


def test_rerank_posts_the_query_and_documents_and_returns_scores(monkeypatch, voyage_key):
    sent = []

    def fake_post(url, headers, json, timeout):
        sent.append((url, json))
        return FakeResponse(
            {"data": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}
        )

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    assert embeddings.rerank("reverse engineering", ["a", "b"]) == [(1, 0.9), (0, 0.1)]
    assert sent == [
        (
            embeddings.VOYAGE_RERANK_URL,
            {"query": "reverse engineering", "documents": ["a", "b"], "model": "rerank-2.5"},
        )
    ]


def test_contextualized_text_prefixes_the_source_of_the_chunk():
    assert (
        embeddings.contextualized_text("Titre", "Chaîne", "Faits", "- Un fait")
        == "Titre — Chaîne — Faits\n- Un fait"
    )
    assert (
        embeddings.contextualized_text("Titre", None, "Faits", "- Un fait")
        == "Titre — Faits\n- Un fait"
    )
