"""Library charts: aggregations (`library_charts`), `/stats` page and `/api/stats/charts`."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.llm.usage import llm_spend_by_month
from app.services.videos.charts import (
    MONTHS_WINDOW,
    TOP_CHANNELS,
    library_chart_data,
    monthly_view,
    purged_media_by_month,
)

NOW = datetime(2026, 10, 9, tzinfo=UTC)


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


def add_channel(db, name):
    channel = Channel(name=name, url=f"https://youtube.com/@{name}", yt_channel_id=f"UC-{name}")
    db.add(channel)
    db.flush()
    return channel


def add_video(
    db, channel, key, *, size=0, added=NOW, short=False, video=True, audio=False, transcript=False
):
    path = f"/media/{key}"
    db.add(
        Video(
            channel_id=channel.id if channel else None,
            yt_video_id=key,
            title=key,
            url=f"https://youtube.com/{'shorts/' if short else 'watch?v='}{key}",
            folder_path=path,
            video_path=f"{path}/v.mp4" if video else None,
            audio_path=f"{path}/a.m4a" if audio else None,
            transcript_path=f"{path}/transcript.txt" if transcript else None,
            file_size_bytes=size,
            downloaded_at=added,
        )
    )
    db.commit()


def test_empty_library(db):
    data = library_chart_data(db, now=NOW)
    assert data["total_cards"] == 0
    assert data["storage_by_channel"] == []
    assert len(data["monthly"]) == MONTHS_WINDOW
    assert all(month["cards_added"] == 0 for month in data["monthly"])
    assert TestClient(app).get("/stats").status_code == 200


def test_channel_and_format_aggregation(db):
    big, small = add_channel(db, "Big"), add_channel(db, "Small")
    add_video(db, big, "a", size=300, transcript=True)
    add_video(db, big, "b", size=100, short=True, video=False, audio=True)
    add_video(db, small, "c", size=50, video=False, audio=True)
    add_video(db, None, "d", size=0, video=False)

    data = library_chart_data(db, now=NOW)

    assert [row["name"] for row in data["storage_by_channel"]] == ["Big", "Small"]
    assert data["storage_by_channel"][0]["bytes"] == 400
    assert data["storage_by_channel"][0]["percent"] == 100
    big_cards = next(row for row in data["cards_by_channel"] if row["name"] == "Big")
    assert (big_cards["cards"], big_cards["shorts"], big_cards["transcripts"]) == (2, 1, 1)
    assert {row["label"]: row["bytes"] for row in data["storage_by_kind"]} == {
        "Vidéos": 350,
        "Shorts": 100,
    }
    assert {row["label"]: row["count"] for row in data["cards_by_format"]} == {
        "Vidéo seule": 1,
        "Audio seul": 2,
        "Vidéo + audio": 0,
        "Sans média": 1,
    }
    assert any(row["name"] == "Sans chaîne" for row in data["cards_by_channel"])
    assert data["storage_by_channel"][0]["channel_id"] == big.id
    assert (
        next(r for r in data["cards_by_channel"] if r["name"] == "Sans chaîne")["channel_id"]
        is None
    )


def test_channels_beyond_top_are_folded_into_others(db):
    for index in range(TOP_CHANNELS + 3):
        add_video(db, add_channel(db, f"c{index}"), f"v{index}", size=100 + index)

    rows = library_chart_data(db, now=NOW)["storage_by_channel"]

    assert len(rows) == TOP_CHANNELS + 1
    assert rows[-1]["name"] == "Autres (3)"
    assert rows[-1]["bytes"] == 100 + 101 + 102


def test_monthly_window_and_cumulative_bytes(db):
    channel = add_channel(db, "Chan")
    add_video(db, channel, "old", size=1000, added=datetime(2024, 1, 5, tzinfo=UTC))
    add_video(db, channel, "sep", size=10, added=datetime(2026, 9, 2, tzinfo=UTC))
    add_video(db, channel, "oct1", size=20, added=datetime(2026, 10, 1, tzinfo=UTC))
    add_video(db, channel, "oct2", size=30, added=datetime(2026, 10, 8, tzinfo=UTC))

    monthly = library_chart_data(db, now=NOW)["monthly"]

    assert monthly[0]["label"] == "11/25"
    assert monthly[-1]["label"] == "10/26"
    assert monthly[-1]["cards_added"] == 2
    assert monthly[-2]["cards_added"] == 1
    assert monthly[0]["cumulative_bytes"] == 1000
    assert monthly[-1]["cumulative_bytes"] == 1060
    assert monthly[-1]["bytes_percent"] == 100


def test_stats_page_and_api(db):
    add_video(db, add_channel(db, "Nota Bene"), "a", size=2048)

    page = TestClient(app).get("/stats")
    assert page.status_code == 200
    assert "Nota Bene" in page.text
    assert "Stockage par chaîne" in page.text

    payload = TestClient(app).get("/api/stats/charts").json()
    assert payload["total_cards"] == 1
    assert payload["total_bytes"] == 2048
    # Everything the page shows around the charts, not only `library_chart_data`.
    assert [kind["percent"] for kind in payload["storage_by_kind"] if kind["bytes"]] == [100.0]
    assert [item["percent"] for item in payload["cards_by_format"] if item["count"]] == [100.0]
    assert payload["quota_bytes"] > 0
    assert payload["quota_percent"] == round(2048 / payload["quota_bytes"] * 100, 1)
    assert payload["purged"]["total"] == 0
    assert payload["spend"]["total"] == 0
    assert len(payload["monthly"]) == MONTHS_WINDOW


def test_monthly_view_drops_leading_empty_months_and_tells_the_story(db):
    channel = add_channel(db, "Chan")
    add_video(db, channel, "aug", size=10, added=datetime(2026, 8, 2, tzinfo=UTC))
    add_video(db, channel, "oct1", size=20, added=datetime(2026, 10, 1, tzinfo=UTC))
    add_video(db, channel, "oct2", size=30, added=datetime(2026, 10, 8, tzinfo=UTC))
    add_video(db, channel, "oct3", size=40, added=datetime(2026, 10, 9, tzinfo=UTC))

    view = monthly_view(library_chart_data(db, now=NOW)["monthly"])

    assert [m["short_label"] for m in view["months"]] == ["août", "sept", "oct"]
    assert view["story"] == "4 fiches ajoutées en 3 mois, dont 3 en octobre."
    assert view["current_cards"] == 3
    assert view["current_bytes"] == 90
    assert view["delta_percent"] is None  # September is empty: no ratio
    assert view["average_cards"] == 1
    assert view["curve_line"].startswith("0.0,") and view["curve_line"].endswith(",0.0")


def test_monthly_view_empty_and_single_month(db):
    assert monthly_view(library_chart_data(db, now=NOW)["monthly"])["story"] is None

    add_video(db, add_channel(db, "Chan"), "oct", size=5, added=NOW)
    view = monthly_view(library_chart_data(db, now=NOW)["monthly"])
    assert len(view["months"]) == 1
    assert view["story"] == "1 fiche ajoutée en octobre."
    assert view["curve_area"].startswith("0,100 0,")


def add_job(db, kind, cost, created):
    db.add(
        LlmJob(
            kind=kind,
            provider="anthropic",
            prompt="p",
            status="done",
            cost_usd=cost,
            created_at=created,
        )
    )
    db.commit()


def test_llm_spend_by_month_groups_kinds_and_drops_leading_empty_months(db):
    add_job(db, "generate", 1.0, datetime(2026, 8, 3, tzinfo=UTC))
    add_job(db, "auto_notes", 0.5, datetime(2026, 10, 1, tzinfo=UTC))
    add_job(db, "library_chat", 0.25, datetime(2026, 10, 5, tzinfo=UTC))
    add_job(db, "mystery", 0.25, datetime(2026, 10, 6, tzinfo=UTC))
    add_job(db, "generate", None, datetime(2026, 10, 7, tzinfo=UTC))  # no recorded cost: ignored
    add_job(db, "generate", 9.0, datetime(2024, 1, 1, tzinfo=UTC))  # before the window

    spend = llm_spend_by_month(db, now=NOW)

    assert [m["short_label"] for m in spend["months"]] == ["août", "sept", "oct"]
    october = spend["months"][-1]
    assert october["total"] == 1.0
    assert [p["cost"] for p in october["parts"]] == [0.5, 0.0, 0.25, 0.25]
    assert october["height"] == 100
    assert spend["total"] == 2.0
    assert spend["current"] == 1.0
    assert TestClient(app).get("/stats").text.count("Dépenses en modèle") == 1


def test_llm_spend_absent_without_cost(db):
    assert llm_spend_by_month(db, now=NOW)["months"] == []
    assert "Dépenses en modèle" not in TestClient(app).get("/stats").text


def test_purged_media_by_month_counts_purge_jobs_per_month(db):
    def job(status, when):
        db.add(DownloadJob(status=status, message="x", created_at=when))

    job("purged", datetime(2026, 8, 3, tzinfo=UTC))
    job("purged", datetime(2026, 10, 1, tzinfo=UTC))
    job("purged", datetime(2026, 10, 8, tzinfo=UTC))
    job("failed", datetime(2026, 10, 8, tzinfo=UTC))
    job("purged", datetime(2024, 1, 1, tzinfo=UTC))
    db.commit()

    data = purged_media_by_month(db, NOW)

    assert [m["short_label"] for m in data["months"]] == ["août", "sept", "oct"]
    assert [m["count"] for m in data["months"]] == [1, 0, 2]
    assert data["total"] == 3
    assert data["current"] == 2
    assert data["months"][-1]["percent"] == 100


def test_purged_media_card_only_when_something_was_purged(db):
    client = TestClient(app)
    assert "Médias supprimés automatiquement" not in client.get("/stats").text
    db.add(DownloadJob(status="purged", message="x"))
    db.commit()
    assert "Médias supprimés automatiquement" in client.get("/stats").text
