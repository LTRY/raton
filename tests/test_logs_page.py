"""The logs page (`logs.html`): French status badges, filters, search, day grouping and pagination."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.job_log import LOG_PAGE_SIZE
from front import logs as job_logs
from tests.site import site_client


@pytest.fixture
def logs_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.pop(get_db, None)


def add_job(db, status, message="msg", *, hours_ago=0.0, channel=None, video=None):
    # created_at is naive UTC, as SQLite's `now()` default stores it.
    created = (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(tzinfo=None)
    job = DownloadJob(
        status=status, message=message, channel=channel, video=video, created_at=created
    )
    db.add(job)
    db.commit()
    return job


def add_channel_video(db, name="Nota Bene", title="Les routes de la soie"):
    channel = Channel(name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}")
    db.add(channel)
    db.flush()
    video = Video(
        channel=channel,
        yt_video_id=f"id-{title}",
        title=title,
        url="https://youtube.com/watch?v=x",
        media_type="metadata",
        folder_path="/media/x",
    )
    db.add(video)
    db.commit()
    return channel, video


def get_logs(path="/logs"):
    response = site_client().get(path)
    assert response.status_code == 200
    return response.text


def test_statuses_render_as_french_badges_with_an_icon(logs_db):
    for status in (
        "queued",
        "running",
        "downloaded",
        "metadata",
        "failed",
        "warning",
        "skipped",
        "purged",
    ):
        add_job(logs_db, status)

    html = get_logs()

    for label in (
        "En file",
        "En cours",
        "Téléchargé",
        "Métadonnées",
        "Échec",
        "Avertissement",
        "Ignoré",
        "Purgé",
    ):
        assert f"</svg>{label}" in html
    assert "log-badge-error" in html and "log-badge-ok" in html and "log-badge-info" in html
    assert ">failed<" not in html


def test_unknown_status_falls_back_to_a_neutral_badge(logs_db):
    add_job(logs_db, "retrying")

    html = get_logs()

    assert "log-badge-neutral" in html
    assert "</svg>retrying" in html


def test_filter_keeps_only_the_statuses_of_its_family(logs_db):
    add_job(logs_db, "failed", "boom")
    add_job(logs_db, "warning", "careful")
    add_job(logs_db, "skipped", "ignored")
    add_job(logs_db, "downloaded", "fine")

    errors = get_logs("/logs?status=errors")
    warnings = get_logs("/logs?status=warnings")

    assert "boom" in errors and "careful" not in errors and "fine" not in errors
    assert "careful" in warnings and "ignored" in warnings and "boom" not in warnings


def test_unknown_filter_shows_everything(logs_db):
    add_job(logs_db, "failed", "boom")
    add_job(logs_db, "downloaded", "fine")

    html = get_logs("/logs?status=nonsense")

    assert "boom" in html and "fine" in html


def test_filter_counts_and_summary_ignore_the_search(logs_db):
    add_job(logs_db, "failed", "recent failure", hours_ago=1)
    add_job(logs_db, "failed", "old failure", hours_ago=72)
    add_job(logs_db, "warning", "recent warning", hours_ago=2)
    add_job(logs_db, "queued", "waiting")
    add_job(logs_db, "running", "busy")

    html = get_logs("/logs?q=nothing-matches")

    assert "<dt>Erreurs (24 h)</dt><dd>1</dd>" in html
    assert "<dt>Avertissements (24 h)</dt><dd>1</dd>" in html
    assert "<dt>En cours ou en file</dt><dd>2</dd>" in html
    assert "<span>Tout<em>5</em></span>" in html
    assert "<span>Erreurs<em>2</em></span>" in html
    assert "Aucun log ne correspond à ces filtres." in html


def test_search_matches_message_video_title_and_channel_name(logs_db):
    channel, video = add_channel_video(logs_db, name="Nota Bene", title="Les routes de la soie")
    add_job(logs_db, "downloaded", "Téléchargé en 4K", channel=channel, video=video)
    add_job(logs_db, "failed", "yt-dlp a échoué")

    by_title = get_logs("/logs?q=SOIE")
    by_channel = get_logs("/logs?q=nota")
    by_message = get_logs("/logs?q=yt-dlp")

    assert "Les routes de la soie" in by_title and "yt-dlp a échoué" not in by_title
    assert "Les routes de la soie" in by_channel
    assert "yt-dlp a échoué" in by_message and "Les routes de la soie" not in by_message


def test_search_treats_like_wildcards_literally(logs_db):
    add_job(logs_db, "warning", "100% complete")
    add_job(logs_db, "warning", "plain message")

    html = get_logs("/logs?q=100%25")

    assert "100% complete" in html and "plain message" not in html


def test_rows_link_to_the_video_or_the_channel(logs_db):
    channel, video = add_channel_video(logs_db)
    add_job(logs_db, "downloaded", "ok", channel=channel, video=video)
    add_job(logs_db, "metadata", "scan", channel=channel)
    add_job(logs_db, "purged", "cache purge")

    html = get_logs()

    assert f'href="/videos/{video.id}">Les routes de la soie</a>' in html
    assert f'href="/videos?channel_id={channel.id}">Nota Bene</a>' in html
    assert '<span class="log-title">Tâche système</span>' in html


def test_jobs_are_grouped_by_day_newest_first(logs_db):
    add_job(logs_db, "downloaded", "today job")
    add_job(logs_db, "downloaded", "old job", hours_ago=24 * 40)

    html = get_logs()

    assert "<h2>Aujourd’hui</h2>" in html
    assert html.index("today job") < html.index("old job")
    assert html.count('class="log-day"') == 2


def test_day_labels():
    today = date(2026, 10, 9)

    assert job_logs.log_day_label(today, today) == "Aujourd’hui"
    assert job_logs.log_day_label(date(2026, 10, 8), today) == "Hier"
    assert job_logs.log_day_label(date(2026, 10, 5), today) == "Lun. 05 oct. 2026"


def test_long_or_multiline_messages_fold_behind_a_detail(logs_db):
    trace = "ERROR: sign in required\nTraceback (most recent call last):\n  File yt.py"
    long_message = "x" * 400
    add_job(logs_db, "failed", trace)
    add_job(logs_db, "warning", long_message)
    add_job(logs_db, "downloaded", "short")

    html = get_logs()

    assert html.count("Voir le détail") == 2
    assert "<pre>ERROR: sign in required\nTraceback" in html
    assert "x" * 400 in html
    assert "x" * 300 not in html.split("<pre>")[0]


def test_split_log_message():
    assert job_logs.split_log_message("short") == ("short", None)
    summary, detail = job_logs.split_log_message("first\nsecond")
    assert (summary, detail) == ("first", "first\nsecond")
    summary, detail = job_logs.split_log_message("y" * 500)
    assert summary.endswith("…") and len(summary) == job_logs.LOG_MESSAGE_SUMMARY_LENGTH
    assert detail == "y" * 500


def test_pagination_splits_jobs_into_pages(logs_db):
    for index in range(LOG_PAGE_SIZE + 5):
        add_job(logs_db, "downloaded", f"job-{index:03d}", hours_ago=index / 60)

    first = get_logs()
    second = get_logs("/logs?page=2")

    assert "job-000" in first and "job-004" in first
    assert f"job-{LOG_PAGE_SIZE:03d}" not in first
    assert f"job-{LOG_PAGE_SIZE:03d}" in second and "job-000" not in second
    assert 'aria-label="Pagination"' in first
    assert f"{LOG_PAGE_SIZE + 5} jobs" in first


def test_empty_table_shows_a_message(logs_db):
    assert "Aucun log." in get_logs()
