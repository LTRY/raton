"""Digest of the application journal: what a reviewer reads before opening the raw file."""

import json
from datetime import UTC, datetime, timedelta

from app.core.logs_digest import build_digest, load_events, render_digest

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def line(minutes_ago: float, **fields) -> dict:
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="milliseconds")
    return {"ts": ts, "level": "INFO", "logger": "app.x", "msg": fields.get("event", "m"), **fields}


def write(path, events) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def nominal_day() -> list[dict]:
    events = [line(60 * 20, event="app.started")]
    for job in ("scheduled_scan", "scheduled_media_purge", "scheduled_auto_notes"):
        events.append(line(60 * 9, event="job.start", job=job))
        events.append(line(60 * 9 - 1, event="job.end", job=job, duration_ms=60000))
    events.append(
        line(5, event="request", method="GET", path="/videos", status=200, duration_ms=80)
    )
    return events


def test_window_keeps_only_the_last_24_hours_across_rotated_files(tmp_path):
    write(tmp_path / "app.jsonl", [line(10, event="request", path="/a", status=200, duration_ms=5)])
    write(
        tmp_path / "app.jsonl.2026-10-16", [line(60 * 23, event="request", path="/b", status=200)]
    )
    write(
        tmp_path / "app.jsonl.2026-10-10",
        [line(60 * 24 * 7, event="request", path="/old", status=200)],
    )

    events, bad = load_events(tmp_path, since=NOW - timedelta(hours=24))

    assert sorted(e["path"] for e in events) == ["/a", "/b"]
    assert bad == 0


def test_malformed_lines_are_counted_not_fatal(tmp_path):
    (tmp_path / "app.jsonl").write_text(
        'not json\n{"ts": "2026-10-17T11:59:00+00:00", "level": "INFO"}\n'
    )

    events, bad = load_events(tmp_path, since=NOW - timedelta(hours=24))

    assert len(events) == 1
    assert bad == 1


def test_nominal_day_has_no_signal():
    digest = build_digest(nominal_day(), now=NOW, hours=24)

    assert digest.signals == []
    assert digest.counts_by_level["INFO"] == len(nominal_day())


def test_errors_are_grouped_by_signature_ignoring_numbers():
    events = nominal_day() + [
        line(30, event="job.error", level="ERROR", job="x", error="HTTP 500 on video 12"),
        line(20, event="job.error", level="ERROR", job="x", error="HTTP 500 on video 987"),
        line(
            10, event="ext.error", level="ERROR", service="voyage", op="embeddings", error="timeout"
        ),
    ]

    digest = build_digest(events, now=NOW, hours=24)

    counts = sorted(group.count for group in digest.error_groups)
    assert counts == [1, 2]
    assert any("erreurs" in s for s in digest.signals)


def test_missing_scheduled_job_is_a_signal():
    events = [e for e in nominal_day() if e.get("job") != "scheduled_media_purge"]

    digest = build_digest(events, now=NOW, hours=24)

    assert any("scheduled_media_purge" in s and "n'a pas tourné" in s for s in digest.signals)


def test_job_that_started_but_never_ended_is_a_signal():
    events = [
        e
        for e in nominal_day()
        if not (e.get("job") == "scheduled_scan" and e["event"] == "job.end")
    ]

    digest = build_digest(events, now=NOW, hours=24)

    assert any("scheduled_scan" in s and "jamais terminé" in s for s in digest.signals)


def test_server_errors_and_slow_requests_are_reported():
    events = nominal_day() + [
        line(3, event="request", method="GET", path="/stats", status=500, duration_ms=40),
        line(
            2,
            event="request",
            method="GET",
            path="/dashboard",
            status=200,
            duration_ms=2500,
            level="WARNING",
        ),
    ]

    digest = build_digest(events, now=NOW, hours=24)

    assert digest.server_errors == [("GET /stats", 1)]
    assert digest.slowest[0][0] == "GET /dashboard"
    assert any("5xx" in s for s in digest.signals)


def test_restarts_are_counted():
    events = nominal_day() + [line(30, event="app.started"), line(10, event="app.started")]

    digest = build_digest(events, now=NOW, hours=24)

    assert digest.restarts == 3
    assert any("redémarrage" in s for s in digest.signals)


def test_external_calls_are_summarised_per_operation():
    events = nominal_day() + [
        line(40, event="ext.call", service="yt-dlp", op="extract_video_info", duration_ms=1000),
        line(39, event="ext.call", service="yt-dlp", op="extract_video_info", duration_ms=3000),
        line(
            38,
            event="ext.error",
            level="WARNING",
            service="yt-dlp",
            op="list_channel_entries",
            error="HTTP 429",
        ),
    ]

    digest = build_digest(events, now=NOW, hours=24)

    stats = {(s.service, s.op): s for s in digest.external}
    assert stats[("yt-dlp", "extract_video_info")].calls == 2
    assert stats[("yt-dlp", "extract_video_info")].max_ms == 3000
    assert stats[("yt-dlp", "list_channel_entries")].errors == 1


def test_render_is_markdown_and_states_a_nominal_day():
    text = render_digest(build_digest(nominal_day(), now=NOW, hours=24))

    assert text.startswith("# Journal applicatif")
    assert "Aucun signal" in text


def test_render_lists_signals():
    events = nominal_day() + [
        line(1, event="request.error", level="ERROR", path="/x", error="Boom: no")
    ]

    text = render_digest(build_digest(events, now=NOW, hours=24))

    assert "## Signaux" in text
    assert "Boom: no" in text
