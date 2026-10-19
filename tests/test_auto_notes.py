"""Nightly batched notes + short résumé: eligibility, the submit/collect cycle, and the Batch API mapping."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.llm.prompts import build_auto_notes_prompt, split_auto_notes_result
from app.services.llm.provider import AnthropicProvider, BatchEntry
from app.services.rag import auto_notes
from app.services.rag import indexing as rag_indexing
from app.services.rag.auto_notes import (
    AUTO_NOTES_KIND,
    BATCH_ID_KEY,
    BATCH_SUBMITTED_AT_KEY,
    eligible_videos,
    run_auto_notes_sweep,
)
from app.services.settings import (
    AUTO_NOTES_ENABLED_KEY,
    AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY,
    get_setting,
    set_setting,
)

LONG_TRANSCRIPT = "Une phrase du transcript. " * 40  # > MIN_TRANSCRIPT_CHARS
ANSWER = """# Résumé
## Résumé court
Ligne un.
Ligne deux.
Ligne trois.

# Notes
## Faits
- Un fait.
## Dates
Aucun élément identifié.
"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.media = tmp_path
    monkeypatch.setattr(auto_notes, "local_media_path", lambda path: Path(path))
    monkeypatch.setattr(rag_indexing, "local_media_path", lambda path: Path(path))
    return session


def add_video(
    db,
    key,
    *,
    channel=None,
    transcript=LONG_TRANSCRIPT,
    notes=None,
    labels=None,
    url=None,
    age_days=0,
):
    folder = db.media / key
    folder.mkdir()
    transcript_path = folder / "transcript.txt"
    if transcript is not None:
        transcript_path.write_text(transcript, encoding="utf-8")
    if notes is not None:
        (folder / "transcript.notes.txt").write_text(notes, encoding="utf-8")
    video = Video(
        channel_id=channel.id if channel else None,
        yt_video_id=key,
        title=f"Video {key}",
        url=url or f"https://youtube.com/watch?v={key}",
        folder_path=str(folder),
        transcript_path=str(transcript_path) if transcript is not None else None,
        category_labels=labels,
        published_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(video)
    db.commit()
    return video


class FakeProvider(AnthropicProvider):
    """The three calls the sweep makes, recorded; results are whatever the test queued."""

    def __init__(self):
        super().__init__("key", "claude-haiku-5-5")
        self.submitted: list[dict[str, str]] = []
        self.results: dict[str, list[BatchEntry] | None] = {}
        self.fail_submit = False

    def submit_batch(self, prompts, effort="low"):
        if self.fail_submit:
            raise RuntimeError("API down")
        self.submitted.append(prompts)
        return f"batch-{len(self.submitted)}"

    def batch_results(self, batch_id):
        return self.results.get(batch_id)


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    """Indexing is Voyage's business (tests/test_rag_indexing.py); here we only record what is asked."""
    calls = []
    monkeypatch.setattr(auto_notes, "index_video_notes", lambda *args: calls.append(args))
    monkeypatch.setattr(auto_notes, "backfill_note_chunks", lambda db: 0)
    monkeypatch.setattr(auto_notes, "backfill_summary_chunks", lambda db: 0)
    return calls


def entries_for(provider, answer=ANSWER, **overrides):
    return [
        BatchEntry(custom_id, answer, None, "claude-haiku-5-5", 12000, 2000, 0.0012, **overrides)
        for custom_id in provider.submitted[-1]
    ]


# --- prompt / parsing ---------------------------------------------------------


def test_prompt_asks_for_notes_and_a_short_summary_only():
    prompt = build_auto_notes_prompt("LE TRANSCRIPT")

    assert "## Résumé court" in prompt and "## Faits" in prompt
    assert (
        "Résumé complet" not in prompt
        and "Questions suggérées" not in prompt
        and "clickbait" not in prompt
    )
    assert prompt.endswith("LE TRANSCRIPT\n")


def test_split_auto_notes_result_returns_notes_and_summary():
    notes, summary = split_auto_notes_result(ANSWER)

    assert summary == "Ligne un.\nLigne deux.\nLigne trois."
    assert notes.startswith("## Faits") and "Un fait." in notes


def test_split_auto_notes_result_accepts_a_level_2_notes_title():
    # A real answer: "# Résumé" followed by "## Notes" instead of "# Notes".
    answer = ANSWER.replace("# Notes\n## Faits", "## Notes\n\n## Faits")

    notes, summary = split_auto_notes_result(answer)

    assert summary == "Ligne un.\nLigne deux.\nLigne trois."
    assert notes.startswith("## Faits") and "Un fait." in notes
    assert not notes.startswith("## Notes")


def test_split_auto_notes_result_degrades_to_empty_pieces():
    assert split_auto_notes_result("du texte libre") == ("", "")


# --- eligibility --------------------------------------------------------------


def test_eligible_videos_applies_every_rule(db):
    cooking = Channel(
        name="Cuisine", url="https://youtube.com/@c", yt_channel_id="UC1", category_labels="cuisine"
    )
    plain = Channel(name="Plain", url="https://youtube.com/@p", yt_channel_id="UC2")
    db.add_all([cooking, plain])
    db.commit()
    add_video(db, "ok", channel=plain)
    add_video(
        db, "own-label-wins", channel=cooking, labels="science"
    )  # own labels replace the channel's
    add_video(db, "inherited-excluded", channel=cooking)
    add_video(db, "own-excluded", channel=plain, labels="podcasts,Entertainment")
    add_video(db, "short", channel=plain, url="https://youtube.com/shorts/abc")
    add_video(db, "has-notes", channel=plain, notes="## Faits\n- x")
    add_video(db, "tiny", channel=plain, transcript="trop court")
    add_video(db, "no-transcript", channel=plain, transcript=None)

    keys = {video.yt_video_id for video in eligible_videos(db, 100)}

    assert keys == {"ok", "own-label-wins"}


def test_eligible_videos_orders_by_recency_and_respects_the_limit(db):
    for index, age in enumerate([30, 1, 10]):
        add_video(db, f"v{index}", age_days=age)

    assert [video.yt_video_id for video in eligible_videos(db, 2)] == ["v1", "v2"]


def test_eligible_videos_skips_in_flight_and_repeatedly_failing_videos(db):
    in_flight = add_video(db, "in-flight")
    failing = add_video(db, "failing")
    retried = add_video(db, "retried")
    db.add(
        LlmJob(
            kind=AUTO_NOTES_KIND,
            provider="anthropic",
            video_id=in_flight.id,
            prompt="x",
            status="running",
        )
    )
    for _ in range(3):
        db.add(
            LlmJob(
                kind=AUTO_NOTES_KIND,
                provider="anthropic",
                video_id=failing.id,
                prompt="x",
                status="failed",
            )
        )
    db.add(
        LlmJob(
            kind=AUTO_NOTES_KIND,
            provider="anthropic",
            video_id=retried.id,
            prompt="x",
            status="failed",
        )
    )
    db.commit()

    assert [video.yt_video_id for video in eligible_videos(db, 100)] == ["retried"]


def test_the_exclusion_list_is_read_from_the_settings(db):
    add_video(db, "science", labels="science")
    add_video(db, "cuisine", labels="cuisine")
    set_setting(db, AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY, "science")
    db.commit()

    assert [video.yt_video_id for video in eligible_videos(db, 100)] == ["cuisine"]


# --- the sweep ----------------------------------------------------------------


def test_first_sweep_submits_a_batch_and_records_it(db):
    add_video(db, "a")
    add_video(db, "b")
    provider = FakeProvider()

    result = run_auto_notes_sweep(db, provider)

    assert result.submitted == 2
    assert len(provider.submitted[0]) == 2
    assert all("# Notes" in prompt for prompt in provider.submitted[0].values())
    jobs = db.scalars(select(LlmJob)).all()
    assert {job.status for job in jobs} == {"running"} and {job.kind for job in jobs} == {
        AUTO_NOTES_KIND
    }
    assert get_setting(db, BATCH_ID_KEY, "") == "batch-1"
    # The transcript lives in the batch, not in the database.
    assert all(len(job.prompt) < 50 for job in jobs)


def test_batch_size_is_capped_at_100(db, monkeypatch):
    monkeypatch.setattr(auto_notes, "BATCH_SIZE", 3)
    for index in range(5):
        add_video(db, f"v{index}", age_days=index)
    provider = FakeProvider()

    assert run_auto_notes_sweep(db, provider).submitted == 3


def test_next_sweep_applies_results_then_submits_the_next_batch(db, no_embeddings):
    first = add_video(db, "first", age_days=1)
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    provider.results["batch-1"] = entries_for(provider)
    add_video(db, "later")

    result = run_auto_notes_sweep(db, provider)

    assert (result.collected, result.failed, result.submitted) == (1, 0, 1)
    folder = Path(first.folder_path)
    assert (folder / "transcript.notes.txt").read_text(encoding="utf-8").startswith("## Faits")
    assert (folder / "transcript.summary_short.txt").read_text(
        encoding="utf-8"
    ) == "Ligne un.\nLigne deux.\nLigne trois."
    assert no_embeddings == [
        (
            first.id,
            (folder / "transcript.notes.txt").read_text(encoding="utf-8"),
            "Ligne un.\nLigne deux.\nLigne trois.",
        )
    ]
    job = db.scalars(select(LlmJob).where(LlmJob.video_id == first.id)).one()
    assert (job.status, job.model, job.input_tokens, job.output_tokens, job.cost_usd) == (
        "applied",
        "claude-haiku-5-5",
        12000,
        2000,
        0.0012,
    )
    # The next batch holds the video that arrived since, not the one just done (it has notes now).
    assert len(provider.submitted[1]) == 1


def test_a_batch_still_in_progress_blocks_a_new_submission(db):
    add_video(db, "a")
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    add_video(db, "b")  # batch-1 has no results yet: provider.results["batch-1"] is None

    result = run_auto_notes_sweep(db, provider)

    assert result.status == "lot en cours" and result.submitted == 0
    assert len(provider.submitted) == 1


def test_failed_requests_are_marked_failed_and_do_not_write_anything(db):
    video = add_video(db, "a")
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    provider.results["batch-1"] = [
        BatchEntry(cid, None, "errored : overloaded", "claude-haiku-5-5", 10, 0, 0.0)
        for cid in provider.submitted[0]
    ]

    result = run_auto_notes_sweep(db, provider)

    job = db.scalars(select(LlmJob)).first()
    assert (job.status, result.failed, result.collected) == ("failed", 1, 0)
    assert "overloaded" in job.error
    assert not (Path(video.folder_path) / "transcript.notes.txt").exists()


def test_an_answer_without_notes_fails_the_job(db):
    video = add_video(db, "a")
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    provider.results["batch-1"] = entries_for(provider, answer="Désolé, je ne peux pas.")

    run_auto_notes_sweep(db, provider)

    assert db.scalars(select(LlmJob)).first().status == "failed"
    assert not (Path(video.folder_path) / "transcript.notes.txt").exists()


def test_a_summary_written_by_hand_is_not_overwritten(db):
    video = add_video(db, "a")
    (Path(video.folder_path) / "transcript.summary_short.txt").write_text(
        "Le mien.", encoding="utf-8"
    )
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    provider.results["batch-1"] = entries_for(provider)

    run_auto_notes_sweep(db, provider)

    assert (Path(video.folder_path) / "transcript.summary_short.txt").read_text(
        encoding="utf-8"
    ) == "Le mien."
    assert (Path(video.folder_path) / "transcript.notes.txt").exists()


def test_a_fully_failed_batch_skips_the_next_submission_once(db):
    for index in range(3):
        add_video(db, f"v{index}", age_days=index)
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    provider.results["batch-1"] = [
        BatchEntry(cid, None, "errored", None) for cid in provider.submitted[0]
    ]

    skipped = run_auto_notes_sweep(db, provider)
    retried = run_auto_notes_sweep(db, provider)

    assert skipped.status.startswith("pause") and skipped.submitted == 0
    assert retried.submitted == 3  # failed once each: still under the cap of 3


def test_a_batch_lost_for_more_than_36_hours_is_given_up_on(db):
    add_video(db, "a")
    provider = FakeProvider()
    run_auto_notes_sweep(db, provider)
    set_setting(db, BATCH_SUBMITTED_AT_KEY, (datetime.now(UTC) - timedelta(hours=40)).isoformat())
    db.commit()

    result = run_auto_notes_sweep(db, provider)

    assert get_setting(db, BATCH_ID_KEY, "") != "batch-1"
    assert result.failed == 1


def test_a_disabled_sweep_does_nothing(db):
    add_video(db, "a")
    set_setting(db, AUTO_NOTES_ENABLED_KEY, "false")
    db.commit()
    provider = FakeProvider()

    result = run_auto_notes_sweep(db, provider)

    assert result.status == "désactivé" and provider.submitted == []


def test_a_failed_submission_leaves_no_running_job_behind(db):
    add_video(db, "a")
    provider = FakeProvider()
    provider.fail_submit = True

    with pytest.raises(RuntimeError):
        run_auto_notes_sweep(db, provider)

    assert db.scalars(select(LlmJob)).all() == []
    assert get_setting(db, BATCH_ID_KEY, "") == ""


# --- the Anthropic Batch API mapping -------------------------------------------


def fake_anthropic(monkeypatch, *, status="ended", items=()):
    """Stands in for the `anthropic` module: records batches.create, serves canned retrieve/results."""
    created = []
    batches = SimpleNamespace(
        create=lambda **kwargs: created.append(kwargs) or SimpleNamespace(id="msgbatch_1"),
        retrieve=lambda batch_id: SimpleNamespace(processing_status=status),
        results=lambda batch_id: iter(items),
    )
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **kwargs: client)
    )
    return created


def succeeded(custom_id, text, *, stop_reason="end_turn", input_tokens=1000, output_tokens=500):
    message = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        model="claude-haiku-5-5",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )
    return SimpleNamespace(
        custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=message)
    )


def test_submit_batch_sends_one_low_effort_request_per_prompt(monkeypatch):
    created = fake_anthropic(monkeypatch)

    batch_id = AnthropicProvider("key", "claude-haiku-5-5").submit_batch(
        {"job-1": "P1", "job-2": "P2"}
    )

    assert batch_id == "msgbatch_1"
    requests = created[0]["requests"]
    assert [request["custom_id"] for request in requests] == ["job-1", "job-2"]
    params = requests[0]["params"]
    assert params["model"] == "claude-haiku-5-5"
    assert params["output_config"] == {"effort": "low"}
    assert params["messages"] == [{"role": "user", "content": "P1"}]
    assert params["max_tokens"] > 4096


def test_batch_results_is_none_while_the_batch_is_processing(monkeypatch):
    fake_anthropic(monkeypatch, status="in_progress")

    assert AnthropicProvider("key", "claude-haiku-5-5").batch_results("msgbatch_1") is None


def test_batch_results_maps_outcomes_and_halves_the_price(monkeypatch):
    errored = SimpleNamespace(
        custom_id="job-2",
        result=SimpleNamespace(
            type="errored", error=SimpleNamespace(error=SimpleNamespace(message="Overloaded"))
        ),
    )
    expired = SimpleNamespace(custom_id="job-3", result=SimpleNamespace(type="expired"))
    fake_anthropic(
        monkeypatch,
        items=[
            succeeded("job-1", "du texte", input_tokens=1_000_000, output_tokens=1_000_000),
            errored,
            expired,
            succeeded("job-4", "coupé", stop_reason="max_tokens"),
        ],
    )

    entries = {
        e.custom_id: e
        for e in AnthropicProvider("key", "claude-haiku-5-5").batch_results("msgbatch_1")
    }

    assert entries["job-1"].text == "du texte"
    # Haiku 5.5 is 0.10 + 0.50 $/M; the batch charges half, and a prompt over 100k tokens is on the 5x tier.
    assert entries["job-1"].cost_usd == pytest.approx(
        (1_000_000 * 0.50 + 1_000_000 * 2.50) / 1e6 * 0.5
    )
    assert entries["job-2"].text is None and "Overloaded" in entries["job-2"].error
    assert entries["job-3"].text is None and "expired" in entries["job-3"].error
    # A truncated answer is a failure, but its tokens were billed.
    assert (
        entries["job-4"].text is None
        and entries["job-4"].output_tokens == 500
        and entries["job-4"].cost_usd > 0
    )


# --- /settings ----------------------------------------------------------------


@pytest.fixture
def settings_client():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from app.db.session import get_db
    from app.main import app

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_settings_page_shows_the_card_with_the_defaults(settings_client):
    client, db = settings_client
    set_setting(db, auto_notes.LAST_RUN_AT_KEY, "2026-10-12T12:00:00+00:00")
    set_setting(db, auto_notes.LAST_RUN_SUMMARY_KEY, "3 appliquée(s), 0 en échec · 100 soumise(s)")
    db.commit()

    html = client.get("/settings").text

    assert 'id="auto-notes"' in html
    assert 'name="auto_notes_enabled" checked' in html
    for label in ("cuisine", "amv", "musique", "sport", "entertainment"):
        assert f'name="auto_notes_excluded_categories" value="{label}" checked' in html
    assert "100 soumise(s)" in html


def test_settings_form_saves_the_switch_and_the_exclusions(settings_client):
    from app.web.routes import settings as settings_routes

    _, db = settings_client

    settings_routes.settings_form(
        "/media",
        1.0,
        "",
        db,
        auto_notes_enabled="",
        auto_notes_excluded_categories=["Science", "cuisine"],
    )

    assert get_setting(db, AUTO_NOTES_ENABLED_KEY, "true") == "false"
    assert get_setting(db, AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY, "") == "science,cuisine"
