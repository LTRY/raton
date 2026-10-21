"""`/rag` page: the buckets, the next batch and the statement count of the page."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.models.video_note_chunk import VideoNoteChunk
from app.services.common.settings import AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY, set_setting
from app.services.rag.auto_notes import (
    AUTO_NOTES_KIND,
    BATCH_ID_KEY,
    BATCH_SIZE,
    BATCH_SUBMITTED_AT_KEY,
    MAX_FAILURES_PER_VIDEO,
)
from app.services.rag.dashboard import next_sweep_at, rag_dashboard_data

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
MAX_STATEMENTS = 40


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
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    session.statements = statements
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_channel(db, name="Chaîne", labels=None):
    channel = Channel(
        name=name,
        url=f"https://youtube.com/@{name}",
        yt_channel_id=f"UC-{name}",
        category_labels=labels,
    )
    db.add(channel)
    db.flush()
    return channel


def add_video(db, key, channel, *, transcript=True, short=False, labels=None, age_days=0):
    video = Video(
        channel_id=channel.id,
        yt_video_id=key,
        title=f"Titre {key}",
        url=f"https://youtube.com/{'shorts/' if short else 'watch?v='}{key}",
        folder_path=f"/media/{key}",
        transcript_path=f"/media/{key}/transcript.txt" if transcript else None,
        category_labels=labels,
        published_at=NOW - timedelta(days=age_days),
    )
    db.add(video)
    db.flush()
    return video


def add_job(db, video, status, *, cost=0.01):
    db.add(
        LlmJob(
            kind=AUTO_NOTES_KIND,
            provider="anthropic",
            video_id=video.id,
            prompt="x",
            status=status,
            cost_usd=cost if status == "applied" else None,
            input_tokens=1000 if status == "applied" else None,
            output_tokens=200 if status == "applied" else None,
            created_at=NOW - timedelta(hours=2),
        )
    )


def add_chunk(db, video, section="Faits"):
    db.add(
        VideoNoteChunk(
            video_id=video.id, section=section, content="- un fait", embedding=[0.0, 0.0, 0.0]
        )
    )


def bucket_counts(data):
    return {bucket["key"]: bucket["count"] for bucket in data["buckets"]}


def test_every_video_lands_in_exactly_one_bucket(db):
    set_setting(db, AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY, "musique")
    channel = add_channel(db)
    indexed = add_video(db, "indexed", channel)
    add_chunk(db, indexed)
    in_batch = add_video(db, "inbatch", channel)
    add_job(db, in_batch, "running")
    abandoned = add_video(db, "abandoned", channel)
    for _ in range(MAX_FAILURES_PER_VIDEO):
        add_job(db, abandoned, "failed")
    add_video(db, "short", channel, short=True)
    add_video(db, "label", channel, labels="musique")
    add_video(db, "notranscript", channel, transcript=False)
    add_video(db, "waiting", channel)
    db.commit()

    data = rag_dashboard_data(db, NOW)

    assert bucket_counts(data) == {
        "indexed": 1,
        "in_batch": 1,
        "waiting": 1,
        "no_transcript": 1,
        "short": 1,
        "label": 1,
        "failed": 1,
    }
    assert sum(bucket["count"] for bucket in data["buckets"]) == data["total_videos"] == 7


def test_channel_labels_apply_when_the_video_has_none(db):
    set_setting(db, AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY, "musique")
    music = add_channel(db, "Musique", labels="musique")
    add_video(db, "a", music)
    db.commit()

    assert bucket_counts(rag_dashboard_data(db, NOW))["label"] == 1


def test_next_batch_is_the_most_recent_waiting_videos_capped_at_the_batch_size(db):
    channel = add_channel(db)
    for index in range(BATCH_SIZE + 5):
        add_video(db, f"v{index}", channel, age_days=index)
    db.commit()

    data = rag_dashboard_data(db, NOW)

    assert data["next_batch"]["size"] == BATCH_SIZE
    assert data["next_batch"]["queue_after"] == 5
    assert data["next_batch"]["nights_left"] == 2
    assert data["next_batch"]["videos"][0]["title"] == "Titre v0"


def test_batch_in_flight_is_reported_with_its_submission_date(db):
    channel = add_channel(db)
    video = add_video(db, "a", channel)
    add_job(db, video, "running")
    set_setting(db, BATCH_ID_KEY, "msgbatch_123")
    set_setting(db, BATCH_SUBMITTED_AT_KEY, (NOW - timedelta(hours=3)).isoformat())
    db.commit()

    pipeline = rag_dashboard_data(db, NOW)["pipeline"]

    assert pipeline["batch_id"] == "msgbatch_123"
    assert pipeline["batch_videos"] == 1
    assert pipeline["abandon_at"] == NOW - timedelta(hours=3) + timedelta(hours=36)
    assert pipeline["state"] in {"in_flight", "no_key"}


def test_costs_and_history_come_from_the_jobs(db):
    channel = add_channel(db)
    for index in range(2):
        add_job(db, add_video(db, f"a{index}", channel), "applied", cost=0.02)
    add_job(db, add_video(db, "f", channel), "failed")
    db.commit()

    data = rag_dashboard_data(db, NOW)

    assert data["jobs"]["applied"] == 2
    assert data["jobs"]["failed"] == 1
    assert data["jobs"]["cost_usd"] == pytest.approx(0.04)
    assert data["jobs"]["avg_cost_usd"] == pytest.approx(0.02)
    today = data["history"][-1]
    assert (today["applied"], today["failed"]) == (2, 1)
    assert len(data["history"]) == 14
    assert len(data["failures"]) == 1


def test_chunk_stats(db):
    channel = add_channel(db)
    video = add_video(db, "a", channel)
    for section in ("Faits", "Dates", "Résumé"):
        add_chunk(db, video, section)
    db.commit()

    chunks = rag_dashboard_data(db, NOW)["chunks"]

    assert chunks["chunks"] == 3
    assert chunks["videos"] == 1
    assert chunks["with_summary"] == 1
    assert chunks["histogram"] == [{"chunks": 3, "videos": 1, "percent": 100.0}]


def test_next_sweep_is_5am_in_paris():
    # 2026-10-14 03:00 UTC is 05:00 CEST: the sweep is due exactly now, so the next one is tomorrow.
    due = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
    assert next_sweep_at(due).hour == 5
    assert next_sweep_at(due).date().isoformat() == "2026-10-15"
    assert next_sweep_at(due - timedelta(hours=1)).date().isoformat() == "2026-10-14"


def test_page_renders_on_an_empty_library(db):
    response = TestClient(app).get("/rag")

    assert response.status_code == 200
    assert "Indexation RAG" in response.text
    assert "Rien en attente" in response.text


def test_page_statement_count_does_not_grow_with_the_library(db):
    channel = add_channel(db)
    for index in range(150):
        video = add_video(db, f"v{index}", channel, age_days=index)
        if index % 3 == 0:
            add_chunk(db, video)
        elif index % 3 == 1:
            add_job(db, video, "applied")
    db.commit()
    db.statements.clear()

    response = TestClient(app).get("/rag")

    assert response.status_code == 200
    assert len(db.statements) <= MAX_STATEMENTS


def test_api_serves_the_page_data_as_json(db):
    channel = add_channel(db)
    indexed = add_video(db, "indexed", channel)
    add_chunk(db, indexed)
    add_video(db, "waiting", channel)
    db.commit()

    payload = TestClient(app).get("/api/rag").json()

    expected = rag_dashboard_data(db)
    assert payload["total_videos"] == expected["total_videos"] == 2
    assert [(bucket["key"], bucket["count"]) for bucket in payload["buckets"]] == [
        (bucket["key"], bucket["count"]) for bucket in expected["buckets"]
    ]
    assert payload["next_batch"]["videos"][0]["title"] == "Titre waiting"
    # Datetimes are ISO 8601; the delay before the sweep is an ISO 8601 duration.
    assert payload["pipeline"]["next_sweep_at"].startswith(
        expected["pipeline"]["next_sweep_at"].date().isoformat()
    )
    assert payload["pipeline"]["next_sweep_in"].startswith("P")
