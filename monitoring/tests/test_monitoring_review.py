import json
import subprocess
from datetime import datetime

from monitoring import review as monitoring_review
from monitoring.review import Review


def make_review(started: str, trigger: str = "scheduled", cost: float | None = 0.12) -> Review:
    return Review(
        id=started[:10] + "-080000",
        started=started,
        trigger=trigger,
        hours=24,
        ok=True,
        cost_usd=cost,
        duration_ms=1000,
        text="**Nominal**\n\nRien à signaler.",
    )


def test_parse_output_reads_the_verdict_and_the_cost():
    payload = json.dumps(
        {"result": "Nominal", "total_cost_usd": 0.2345, "duration_ms": 4200, "is_error": False}
    )

    assert monitoring_review.parse_output(payload) == ("Nominal", 0.2345, 4200, True)


def test_parse_output_survives_text_that_is_not_json():
    assert monitoring_review.parse_output("boom") == ("boom", None, None, False)


def test_command_is_read_only_and_bounded():
    command = monitoring_review.build_command(24, "sonnet", 1.0)

    assert command[:4] == ["claude", "--bare", "-p", "/review-logs 24"]
    assert command[command.index("--max-budget-usd") + 1] == "1.0"
    assert command[command.index("--model") + 1] == "sonnet"
    tools = command[command.index("--allowedTools") + 1 : command.index("--model")]
    assert not [tool for tool in tools if tool in ("Edit", "Write", "Bash")]


def test_review_is_due_once_a_day_from_the_hour_on():
    today = "2026-10-23T08:00:05"
    now = datetime(2026, 10, 23, 8, 0, 30)

    assert not monitoring_review.is_due(datetime(2026, 10, 23, 7, 59), 8, [])
    assert monitoring_review.is_due(now, 8, [])
    assert monitoring_review.is_due(now, 8, [make_review("2026-10-22T08:00:05")])
    assert not monitoring_review.is_due(now, 8, [make_review(today)])
    # A manual run does not replace the scheduled one.
    assert monitoring_review.is_due(now, 8, [make_review(today, trigger="manual")])
    # Catch-up: the container restarted at 15:00 without a review today.
    assert monitoring_review.is_due(datetime(2026, 10, 23, 15, 0), 8, [])


def test_execute_review_stores_the_verdict_and_its_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_review, "REVIEW_DIR", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        out = json.dumps({"result": "Nominal", "total_cost_usd": 0.31, "duration_ms": 9})
        return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")

    monkeypatch.setattr(monitoring_review.subprocess, "run", fake_run)

    review = monitoring_review.execute_review(24, "scheduled", datetime(2026, 10, 23, 8, 0, 1))

    assert review.ok and review.cost_usd == 0.31
    assert monitoring_review.list_reviews() == [review]
    assert monitoring_review.read_review("2026-10-23-080001") == review


def test_execute_review_without_api_key_is_stored_as_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_review, "REVIEW_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    review = monitoring_review.execute_review(24, "manual", datetime(2026, 10, 23, 9, 0, 0))

    assert not review.ok and "ANTHROPIC_API_KEY" in review.text
    assert monitoring_review.list_reviews() == [review]


def test_read_review_refuses_anything_but_a_review_id(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_review, "REVIEW_DIR", tmp_path)

    assert monitoring_review.read_review("../../etc/passwd") is None
    assert monitoring_review.read_review("2026-10-23-999999") is None


def test_reviews_card_shows_the_cost_of_the_last_run_and_of_the_month():
    now = datetime(2026, 10, 23, 12, 0)
    reviews = [make_review("2026-10-23T08:00:05", cost=0.2), make_review("2026-10-22T08:00:05")]

    card = monitoring_review.render_reviews(reviews, busy=False, now=now)

    assert "0,20 $" in card
    assert "Coût des 30 derniers jours : 0,32 $" in card
    assert "Nominal" in card
    assert 'href="/reviews/2026-10-23-080000"' in card


def test_reviews_card_while_running_disables_the_button():
    card = monitoring_review.render_reviews([], busy=True)

    assert "Revue en cours…" in card and "disabled" in card
