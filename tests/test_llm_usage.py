from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.llm_job import LlmJob
from app.services.llm.usage import (
    compute_call_cost_usd,
    compute_job_cost_usd,
    llm_usage_summary,
    max_output_tokens,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_compute_job_cost_usd_uses_the_model_pricing():
    # 1_000_000 input tokens * $1/1M + 200_000 output tokens * $5/1M = $1 + $1 = $2
    cost = compute_job_cost_usd("anthropic", "claude-haiku-4-5", 1_000_000, 200_000)
    assert cost == 2.0


def test_compute_job_cost_usd_is_none_for_non_anthropic_or_unknown_model():
    assert compute_job_cost_usd("mistral", "some-model", 100, 100) is None
    assert compute_job_cost_usd("anthropic", "some-future-model", 100, 100) is None


def test_compute_job_cost_usd_is_none_when_token_counts_are_missing():
    assert compute_job_cost_usd("anthropic", "claude-haiku-4-5", None, 100) is None
    assert compute_job_cost_usd("anthropic", "claude-haiku-4-5", 100, None) is None


def test_haiku_5_5_is_priced_per_call_by_prompt_size():
    # Up to 100K prompt tokens: $0.10 in / $0.50 out per 1M.
    assert round(compute_call_cost_usd("claude-haiku-5-5", 100_000, 10_000), 6) == 0.015
    # Over 100K: the whole call, output included, moves to $0.50 / $2.50.
    assert round(compute_call_cost_usd("claude-haiku-5-5", 100_001, 10_000), 6) == round(
        0.0500005 + 0.025, 6
    )


def test_prompt_tier_counts_cached_tokens():
    # 1K uncached + 99_500 read from cache = 100_500 prompt tokens -> long-prompt tier.
    cost = compute_call_cost_usd("claude-haiku-5-5", 1_000, 0, cache_read_tokens=99_500)
    assert round(cost, 6) == round(1_000 * 0.50 / 1e6 + 99_500 * 0.05 / 1e6, 6)


def test_cache_tokens_are_priced_separately():
    # Haiku 4.5: write $1.25, read $0.10, input $1, output $5 per 1M.
    cost = compute_call_cost_usd(
        "claude-haiku-4-5",
        1_000_000,
        1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )
    assert round(cost, 4) == 1.0 + 1.25 + 0.10 + 5.0


def test_current_sonnet_prices():
    assert (
        compute_call_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0
    )  # $2 + $10, not the cancelled $3/$15
    assert compute_call_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0


def test_max_output_tokens_follows_the_model():
    assert max_output_tokens("claude-haiku-4-5") == 64_000
    assert max_output_tokens("claude-haiku-5-5") == 128_000
    assert max_output_tokens("some-future-model") == 64_000


def add_job(db, **overrides):
    defaults = dict(kind="notes", provider="anthropic", video_id=None, prompt="p", status="applied")
    defaults.update(overrides)
    job = LlmJob(**defaults)
    db.add(job)
    db.commit()
    return job


def test_llm_usage_summary_groups_by_kind_and_ignores_untracked_jobs():
    db = make_session()
    add_job(
        db,
        kind="notes",
        model="claude-haiku-4-5",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.002,
    )
    add_job(
        db,
        kind="notes",
        model="claude-haiku-4-5",
        input_tokens=500,
        output_tokens=100,
        cost_usd=0.001,
    )
    add_job(
        db,
        kind="summary",
        model="claude-haiku-4-5",
        input_tokens=2000,
        output_tokens=400,
        cost_usd=0.004,
    )
    add_job(
        db, kind="clean_transcript", provider="mistral", status="applied"
    )  # no cost, no cached pricing
    add_job(db, kind="notes", status="failed")  # no cost, failed before completion

    summary = llm_usage_summary(db)

    by_kind = {row["kind"]: row for row in summary["by_kind"]}
    assert by_kind["notes"]["job_count"] == 2
    assert by_kind["notes"]["input_tokens"] == 1500
    assert by_kind["notes"]["output_tokens"] == 300
    assert by_kind["notes"]["cost_usd"] == 0.003
    assert by_kind["notes"]["label"] == "Notes structurées"
    assert by_kind["summary"]["job_count"] == 1
    assert "clean_transcript" not in by_kind  # the CLI-provider job has no cost_usd

    assert summary["total_job_count"] == 3
    assert round(summary["total_cost_usd"], 3) == 0.007
    assert summary["untracked_job_count"] == 2  # the CLI job + the failed job


def test_llm_usage_summary_groups_by_model_most_expensive_first():
    db = make_session()
    add_job(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, cost_usd=0.002)
    add_job(db, model="claude-haiku-5-5", input_tokens=1000, output_tokens=200, cost_usd=0.0002)
    add_job(db, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, cost_usd=0.002)

    by_model = llm_usage_summary(db)["by_model"]

    assert [row["model"] for row in by_model] == ["claude-haiku-4-5", "claude-haiku-5-5"]
    assert by_model[0]["job_count"] == 2
    assert by_model[0]["input_tokens"] == 2000


def test_llm_usage_summary_with_no_jobs_at_all():
    db = make_session()

    summary = llm_usage_summary(db)

    assert summary == {
        "by_kind": [],
        "by_model": [],
        "total_cost_usd": 0,
        "total_job_count": 0,
        "untracked_job_count": 0,
    }
