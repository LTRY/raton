"""`/api` LLM requests: notes of a fiche, its discussion, the library chat, `GET /api/llm-jobs`.

The model is never called: `run_llm_job` is replaced, and each test moves the job along by hand
(running with a partial result, done, failed) the way `run_llm_job` would.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.api import llm as llm_api
from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.llm_job import LlmJob
from back.models.video import Video

# Same shape as tests/test_videos.py: the two level-1 headers `split_generation_result` cuts on.
GENERATION_RESULT_TEXT = (
    "# Notes\n## Faits\n- Fait 1\n- Fait 2\n\n## Dates\nAucun élément identifié.\n\n"
    "## Lieux\nAucun élément identifié.\n\n## Acteurs\nAucun élément identifié.\n\n"
    "## Concepts\nAucun élément identifié.\n\n## Relations causales\nAucun élément identifié.\n\n"
    "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
    "## Questions suggérées\n- Question A ?\n- Question B ?\n\n"
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tasks(monkeypatch):
    """The background jobs the routes queued, instead of calling the model or the index."""
    calls = []
    monkeypatch.setattr(llm_api, "run_llm_job", lambda *args: calls.append(("llm", *args)))
    monkeypatch.setattr(
        llm_api, "run_notes_indexing_job", lambda *args: calls.append(("index", *args))
    )
    return calls


@pytest.fixture
def video(db, tmp_path):
    (tmp_path / "transcript.txt").write_text("Bonjour, ceci est le transcript.", encoding="utf-8")
    video = Video(
        yt_video_id="abc",
        title="Fiche",
        url="https://youtube.com/watch?v=abc",
        folder_path=str(tmp_path),
        transcript_path=str(tmp_path / "transcript.txt"),
    )
    db.add(video)
    db.commit()
    return video


def finish(db, job_id, **fields):
    job = db.get(LlmJob, job_id)
    for name, value in fields.items():
        setattr(job, name, value)
    db.commit()


def test_generate_notes_streams_then_writes_and_indexes_them(client, db, video, tasks):
    queued = client.post(f"/api/videos/{video.id}/notes/generate")
    job_id = queued.json()["job_id"]
    finish(db, job_id, status="running", result="# Résumé\n## Résumé court\nLigne 1.")
    running = client.get(queued.json()["status_url"]).json()
    finish(db, job_id, status="done", result=GENERATION_RESULT_TEXT)
    done = client.get(queued.json()["status_url"]).json()
    replayed = client.get(queued.json()["status_url"]).json()

    assert queued.status_code == 202
    assert queued.json()["status_url"] == f"/api/llm-jobs/{job_id}"
    assert running["status"] == "pending"
    assert running["partial_short_summary"] == "Ligne 1."
    assert done["status"] == "done"
    assert done["kind"] == "generate"
    assert "Fait 1" in done["documents"]["notes"]
    assert done["documents"]["suggested_questions"] == ["Question A ?", "Question B ?"]
    assert replayed["documents"] == done["documents"]
    # Indexed once, after the first poll that wrote the notes; the replay writes nothing.
    assert [call[0] for call in tasks] == ["llm", "index"]
    assert tasks[1][1] == video.id


def test_generate_notes_without_a_transcript_is_refused(client, db, video, tasks):
    video.transcript_path = None
    db.commit()

    response = client.post(f"/api/videos/{video.id}/notes/generate")

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Génération impossible : ")
    assert tasks == []


def test_a_question_on_a_fiche_is_answered_into_its_discussion(client, db, video, tasks):
    empty = client.post(f"/api/videos/{video.id}/chat", json={"question": "   "})
    queued = client.post(
        f"/api/videos/{video.id}/chat", json={"question": " De quoi parle-t-on ? "}
    )
    finish(db, queued.json()["job_id"], status="done", result="Du transcript.")
    done = client.get(queued.json()["status_url"]).json()
    cleared = client.delete(f"/api/videos/{video.id}/chat")

    assert empty.status_code == 400
    assert empty.json() == {"detail": "La question est vide."}
    assert db.get(LlmJob, queued.json()["job_id"]).question == "De quoi parle-t-on ?"
    assert done["status"] == "done"
    assert done["chat_messages"] == [
        {"role": "user", "content": "De quoi parle-t-on ?"},
        {"role": "assistant", "content": "Du transcript."},
    ]
    assert cleared.status_code == 204
    assert client.get(f"/api/videos/{video.id}").json()["documents"]["chat_messages"] == []


def test_the_library_chat_shows_its_tools_then_its_answer(client, db, video, tasks):
    queued = client.post("/api/chat", json={"question": "Quelles vidéos ?"})
    job_id = queued.json()["job_id"]
    finish(db, job_id, status="running", tool_calls=json.dumps([{"name": "search_videos"}]))
    running = client.get(f"/api/llm-jobs/{job_id}").json()
    finish(
        db,
        job_id,
        status="done",
        result="Celle-ci.",
        sources=json.dumps({"video_ids": [video.id], "channel_ids": []}),
    )
    done = client.get(f"/api/llm-jobs/{job_id}").json()
    chat = client.get("/api/chat").json()
    conversation_url = f"/api/chat/conversations/{queued.json()['conversation_id']}"
    opened = client.get(conversation_url).json()
    deleted = client.delete(conversation_url)

    assert running["tool_calls"] == [{"name": "search_videos"}]
    assert done["status"] == "done"
    answer = done["library_chat"]["messages"][1]
    assert answer["content"] == "Celle-ci."
    assert answer["citations"] == [{"video_id": video.id, "title": "Fiche"}]
    assert chat["messages"] == done["library_chat"]["messages"]
    assert chat["total_video_count"] == 1
    assert chat["conversation_id"] == queued.json()["conversation_id"]
    assert chat["title"] == "Quelles vidéos ?"
    assert [item["title"] for item in chat["conversations"]] == ["Quelles vidéos ?"]
    assert opened == chat
    assert deleted.status_code == 204
    assert client.get(conversation_url).status_code == 404
    assert client.get("/api/chat").json()["messages"] == []
    assert client.get("/api/chat").json()["conversation_id"] is None


def test_a_failed_job_is_reported_with_its_reason(client, db, video, tasks):
    queued = client.post(f"/api/videos/{video.id}/notes/generate")
    finish(db, queued.json()["job_id"], status="failed", error="quota dépassé")

    response = client.get(queued.json()["status_url"])

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["message"] == "Génération impossible : quota dépassé"


def test_unknown_fiche_or_job(client, db, tasks):
    assert client.post("/api/videos/999/notes/generate").json() == {"detail": "Vidéo introuvable"}
    assert client.post("/api/videos/999/chat", json={"question": "?"}).status_code == 404
    assert client.get("/api/llm-jobs/999").json() == {"detail": "Tâche introuvable"}
