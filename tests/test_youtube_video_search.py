from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.video import Video
from back.services.videos import youtube_search
from back.services.youtube import video_search
from front.formatting import format_relative_age


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def youtube_result(yt_video_id="dQw4w9WgXcQ", title="Never Gonna Give You Up", **fields):
    return {
        "yt_video_id": yt_video_id,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={yt_video_id}",
        "channel_name": "Rick Astley",
        "yt_channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
        "duration_seconds": 213,
        "view_count": 1_600_000_000,
        "published_at": None,
        "is_short": False,
        "thumbnail_url": f"https://i.ytimg.com/vi/{yt_video_id}/hqdefault.jpg",
        **fields,
    }


def test_search_videos_reads_the_youtube_search(monkeypatch):
    requested = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            requested["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            requested["url"] = url
            return {
                "entries": [
                    {
                        "id": "dQw4w9WgXcQ",
                        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        "title": "Never Gonna Give You Up",
                        "channel": "Rick Astley",
                        "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
                        "duration": 213.0,
                        "timestamp": 1_700_000_000,
                        "view_count": 1600000000,
                        "thumbnails": [
                            {"url": "//i.ytimg.com/small.jpg"},
                            {"url": "//i.ytimg.com/big.jpg"},
                        ],
                    },
                    {
                        "id": "abcdefghijk",
                        "url": "https://www.youtube.com/shorts/abcdefghijk",
                        "title": "Un short",
                    },
                    {"id": "UCchannel_not_a_video", "title": "Une chaîne"},
                    None,
                ]
            }

    monkeypatch.setattr(video_search, "YoutubeDL", FakeYoutubeDL)

    results = video_search.search_videos("  rick   astley ", limit=5)

    assert requested["url"] == "ytsearch5:rick astley"
    assert requested["opts"]["extract_flat"] is True
    assert requested["opts"]["extractor_args"] == {"youtubetab": {"approximate_date": [""]}}
    assert results == [
        youtube_result(
            thumbnail_url="https://i.ytimg.com/big.jpg",
            published_at=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        ),
        {
            "yt_video_id": "abcdefghijk",
            "title": "Un short",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "channel_name": None,
            "yt_channel_id": None,
            "duration_seconds": None,
            "view_count": None,
            "published_at": None,
            "is_short": True,
            "thumbnail_url": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
        },
    ]
    assert video_search.search_videos("   ") == []


def test_api_flags_the_videos_already_in_the_library(monkeypatch, front_client):
    db = make_session()
    known = Video(
        yt_video_id="known000001",
        title="Déjà là",
        url="https://www.youtube.com/watch?v=known000001",
        folder_path="/tmp/known",
    )
    db.add(known)
    db.commit()
    monkeypatch.setattr(
        youtube_search,
        "search_videos",
        lambda query: [youtube_result(), youtube_result("known000001", "Déjà là")],
    )

    found = front_client(db).get("/api/youtube/videos", params={"q": "rick"})

    assert found.status_code == 200
    assert [item["existing"] for item in found.json()] == [
        None,
        {"id": known.id, "title": "Déjà là"},
    ]


def test_recherche_page_lists_youtube_videos_with_an_add_form(monkeypatch, front_client):
    db = make_session()
    known = Video(
        yt_video_id="known000001",
        title="Déjà là",
        url="https://www.youtube.com/watch?v=known000001",
        folder_path="/tmp/known",
    )
    db.add(known)
    db.commit()
    monkeypatch.setattr(
        youtube_search,
        "search_videos",
        lambda query: [
            youtube_result(published_at=datetime(2023, 1, 1, tzinfo=UTC)),
            youtube_result("known000001", "Déjà là", is_short=True),
        ],
    )

    page = front_client(db).get("/videos/recherche", params={"q": "rick", "message": "Ok"})

    assert page.status_code == 200
    html = page.text
    assert 'href="/videos/recherche" aria-current="page"' in html
    assert "Rick Astley · 1 600 000 000 vues · il\u00a0y\u00a0a\u00a0" in html
    assert html.count('aria-label="Ouvrir sur YouTube"') == 2
    assert 'href="https://www.youtube.com/watch?v=known000001" target="_blank"' in html
    assert '<span class="youtube-search-duration">3:33</span>' in html
    assert (
        '<input type="hidden" name="url" value="https://www.youtube.com/watch?v=dQw4w9WgXcQ">'
        in html
    )
    assert '<input type="hidden" name="media_type" value="metadata">' in html
    # Coming back after an addition must not replay the previous toast.
    assert '<input type="hidden" name="next" value="/videos/recherche?q=rick">' in html
    assert f'<a class="csv-import-badge" href="/videos/{known.id}">Dans la bibliothèque</a>' in html
    assert html.count('action="/videos/download"') == 1
    assert "Short" in html


def test_recherche_page_without_query_does_not_call_youtube(monkeypatch, front_client):
    db = make_session()
    monkeypatch.setattr(
        youtube_search, "search_videos", lambda query: (_ for _ in ()).throw(AssertionError)
    )

    html = front_client(db).get("/videos/recherche").text

    assert 'placeholder="Rechercher sur YouTube"' in html
    assert "youtube-search-list" not in html


def test_recherche_page_reports_a_failed_youtube_search(monkeypatch, front_client):
    db = make_session()
    monkeypatch.setattr(
        youtube_search,
        "search_videos",
        lambda query: (_ for _ in ()).throw(RuntimeError("réseau")),
    )

    html = front_client(db).get("/videos/recherche", params={"q": "rick"}).text

    assert "Recherche YouTube impossible : réseau" in html


def test_relative_age_reads_like_youtube():
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert format_relative_age(datetime(2026, 10, 25, tzinfo=UTC), now) == "aujourd’hui"
    assert format_relative_age(datetime(2026, 10, 24, tzinfo=UTC), now) == "il y a 1 jour"
    assert format_relative_age(datetime(2026, 10, 10, tzinfo=UTC), now) == "il y a 2 semaines"
    assert format_relative_age(datetime(2026, 7, 25, tzinfo=UTC), now) == "il y a 3 mois"
    assert format_relative_age(datetime(2023, 10, 25, tzinfo=UTC), now) == "il y a 3 ans"
