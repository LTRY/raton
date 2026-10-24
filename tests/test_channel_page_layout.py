"""The channel page (`channel_videos.html`): sort, filters, cards and the shorts mosaic."""

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.videos.library_view import LIBRARY_PAGE_SIZE
from front.library import shorts_feature_flags
from tests.site import site_client
from tests.users import mine, user_id

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def make_client(keywords=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    channel = Channel(
        name="Ma chaîne",
        url="https://youtube.com/@ma",
        yt_channel_id="UC1",
        keywords=json.dumps(keywords) if keywords is not None else None,
    )
    db.add(channel)
    db.flush()
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    return site_client(), db, channel


def add_video(db, channel, key, *, rating=0, is_new=False, short=False, age_days=0, **extra):
    video = Video(
        channel_id=channel.id,
        yt_video_id=key,
        title=f"Titre {key}",
        url=f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{key}",
        published_at=NOW - timedelta(days=age_days),
        **{"folder_path": "/x", "video_path": "/x/video.mp4", "media_type": "video"} | extra,
        user_states=mine(rating=rating, is_new=is_new),
    )
    db.add(video)
    db.commit()
    return video


def titles_in_order(html):
    return re.findall(r'title="(Titre [^"]+)">', html)


def get_channel_page(client, channel, query=""):
    try:
        return client.get(f"/videos?channel_id={channel.id}{query}").text
    finally:
        app.dependency_overrides.clear()


def test_sort_by_rating_lists_the_best_rated_first():
    client, db, channel = make_client()
    add_video(db, channel, "low", rating=1, age_days=1)
    add_video(db, channel, "top", rating=5, age_days=30)
    add_video(db, channel, "mid", rating=3, age_days=2)

    html = get_channel_page(client, channel, "&sort=rated")

    assert titles_in_order(html) == ["Titre top", "Titre mid", "Titre low"]
    assert 'value="rated" checked' in html
    assert "Les mieux notées" in html


def test_the_library_page_offers_the_rating_sort_too():
    client, db, channel = make_client()
    add_video(db, channel, "a", rating=2)
    try:
        html = client.get("/videos?sort=rated").text
    finally:
        app.dependency_overrides.clear()

    assert '<option value="rated" selected>Les mieux notées</option>' in html


def test_default_channel_filters_show_no_pill_and_no_badge():
    client, db, channel = make_client()
    add_video(db, channel, "a")

    html = get_channel_page(client, channel)

    assert 'class="active-filters-row"' not in html
    assert "channel-count-badge" not in html


def test_an_explicit_filter_shows_a_pill_and_a_filter_count():
    client, db, channel = make_client()
    add_video(db, channel, "a", rating=4)

    html = get_channel_page(client, channel, "&asset_filters=1&asset=video&rated=1")

    assert 'class="active-filters-row"' in html
    assert '<span class="channel-count-badge">2</span>' in html


def test_keywords_past_five_hide_behind_a_counter():
    client, db, channel = make_client(keywords=["a", "b", "c", "d", "e", "f", "g"])
    add_video(db, channel, "a")

    html = get_channel_page(client, channel)

    assert html.count("channel-keyword-extra") == 2
    assert "+2" in html
    assert 'id="channel-keywords-toggle"' in html


def test_five_keywords_or_fewer_have_no_counter():
    client, db, channel = make_client(keywords=["a", "b", "c", "d", "e"])
    add_video(db, channel, "a")

    html = get_channel_page(client, channel)

    assert "channel-keyword-extra" not in html
    assert "channel-keywords-toggle" not in html


def test_cards_show_new_chip_and_progress_on_the_thumbnail_without_meta_line():
    client, db, channel = make_client()
    video = add_video(db, channel, "a", is_new=True, rating=5)
    db.add(
        DownloadJob(
            video_id=video.id,
            user_id=user_id(db),
            status="played",
            message=json.dumps(
                {
                    "type": "playback",
                    "action": "Lecture",
                    "media_label": "vidéo",
                    "position_seconds": 300,
                    "duration_seconds": 1000,
                    "watched_seconds": 300,
                }
            ),
        )
    )
    db.commit()

    html = get_channel_page(client, channel)

    assert '<span class="video-row-new">Nouveau</span>' in html
    assert '<span class="video-row-progress"' in html
    assert 'class="video-meta"' not in html
    assert 'class="video-card-progress"' not in html
    assert '<span class="rating-dot"' in html
    assert "rating-tier-5" in html


def test_the_library_cards_keep_their_meta_line_and_text_progress():
    client, db, channel = make_client()
    add_video(db, channel, "a", is_new=True)
    try:
        html = client.get("/videos").text
    finally:
        app.dependency_overrides.clear()

    assert 'class="video-meta"' in html
    assert "video-row-new" not in html
    assert "rating-dot" not in html


def test_shorts_section_is_a_mosaic_with_a_big_tile_for_new_or_top_rated():
    client, db, channel = make_client()
    add_video(db, channel, "new", short=True, is_new=True, age_days=1)
    add_video(db, channel, "star", short=True, rating=5, age_days=2)
    add_video(db, channel, "plain", short=True, rating=2, age_days=3)

    html = get_channel_page(client, channel, "&section=shorts")

    assert "channel-video-grid-shorts" in html
    assert html.count("video-row-feature") == 1
    assert 'name="section" type="radio" value="shorts" checked' in html


def test_shorts_mosaic_still_has_big_tiles_without_new_or_top_rated():
    client, db, channel = make_client()
    for index in range(8):
        add_video(db, channel, f"p{index}", short=True, rating=2, age_days=index)

    html = get_channel_page(client, channel, "&section=shorts")

    assert html.count("video-row-feature") == 2


def test_shorts_feature_flags_mix_priority_and_rhythm_with_a_minimum_gap():
    def cards(*states):
        return [
            SimpleNamespace(is_new=state == "new", rating=5 if state == "star" else 2)
            for state in states
        ]

    plain = ["-"] * 20
    assert [i for i, f in enumerate(shorts_feature_flags(cards(*plain))) if f] == [0, 7, 14]
    one_star = list(plain)
    one_star[3] = "star"
    assert [i for i, f in enumerate(shorts_feature_flags(cards(*one_star))) if f] == [3, 14]
    all_new = shorts_feature_flags(cards(*["new"] * 20))
    assert [i for i, f in enumerate(all_new) if f] == [0, 6, 12, 18]
    assert shorts_feature_flags([]) == []


def test_videos_section_has_no_mosaic_class():
    client, db, channel = make_client()
    add_video(db, channel, "a", is_new=True)

    html = get_channel_page(client, channel)

    assert "channel-video-grid-shorts" not in html
    assert "video-row-feature" not in html


def test_pagination_is_numbered_and_explore_button_imports_older_fiches():
    client, db, channel = make_client()
    for index in range(LIBRARY_PAGE_SIZE * 3):
        add_video(db, channel, f"v{index:03d}", age_days=index)

    html = get_channel_page(client, channel, "&page=2")

    assert 'class="numbered-pagination"' in html
    assert 'aria-current="page">2<' in html
    assert re.search(r'<a class="numbered-pagination-link" href="[^"]*">3</a>', html)
    assert f'action="/channels/{channel.id}/import-metadata"' in html
    assert "Explorer la suite" in html


def test_channel_page_opts_out_of_turbo_preview():
    # A cached preview would replay the cards' entrance animation when the fresh page replaces it.
    client, _, channel = make_client()
    try:
        html = client.get(f"/videos?channel_id={channel.id}").text
    finally:
        app.dependency_overrides.clear()
    assert '<meta name="turbo-cache-control" content="no-preview">' in html


def test_empty_channel_shows_the_raccoon_with_a_known_message():
    from front.routes.videos import CHANNEL_EMPTY_MESSAGES

    client, db, channel = make_client()

    html = get_channel_page(client, channel)

    assert "raccoon-empty.png" in html
    assert "Aucune fiche trouvée" not in html
    message = re.search(r'class="channel-empty-message">([^<]+)<', html).group(1)
    assert (
        message.replace("&#39;", "’") in CHANNEL_EMPTY_MESSAGES or message in CHANNEL_EMPTY_MESSAGES
    )


def test_empty_channel_search_keeps_the_no_result_text():
    client, db, channel = make_client()
    add_video(db, channel, "one")

    html = get_channel_page(client, channel, "&q=zzzz")

    assert "Aucun résultat pour" in html
    assert "raccoon-empty.png" not in html


def test_empty_channel_starts_the_exploration_instead_of_continuing_it():
    client, db, channel = make_client()

    html = get_channel_page(client, channel)

    assert "Commencer l’exploration" in html
    assert "Explorer la suite" not in html
    assert "Récupère les 25 premières fiches depuis YouTube" in html


def test_channel_with_cards_keeps_explore_the_rest():
    client, db, channel = make_client()
    add_video(db, channel, "one")

    html = get_channel_page(client, channel)

    assert "Explorer la suite" in html
    assert "Récupère les 25 fiches suivantes depuis YouTube" in html


def test_explore_form_is_driven_by_raton_and_keeps_its_hint():
    client, _, channel = make_client()
    html = get_channel_page(client, channel)

    # The form leaves the generic async-job binder: Raton and the live cards are its own script.
    assert re.search(r'<form class="channel-explore"[^>]*data-explore[ >]', html)
    assert "data-async-job" not in re.search(r'<form class="channel-explore"[^>]*>', html).group(0)
    assert "data-explore-grid" in html
    assert re.search(
        r"<p data-explore-hint>Récupère les 25 premières fiches depuis YouTube</p>", html
    )
    assert "data-explorer-raton" in html


def test_channel_import_job_status_lists_the_videos_imported_so_far():
    client, db, channel = make_client()
    job = DownloadJob(channel_id=channel.id, status="running", message="Import en cours")
    db.add(job)
    db.commit()
    before = add_video(db, channel, "before")
    db.add(DownloadJob(channel_id=channel.id, video_id=before.id, status="metadata", message="old"))
    db.commit()
    # Rows logged after the queue row belong to this import.
    queued_after = DownloadJob(channel_id=channel.id, status="queued", message="later")
    db.add(queued_after)
    db.commit()
    first = add_video(db, channel, "first")
    db.add(DownloadJob(channel_id=channel.id, video_id=first.id, status="metadata", message="new"))
    db.commit()

    payload = client.get(f"/api/jobs/{queued_after.id}").json()

    assert payload["done"] is False
    assert payload["videos"] == [{"id": first.id, "title": "Titre first"}]
    # A job that never listed videos (download, playback...) has no "videos" key.
    done = DownloadJob(channel_id=channel.id, status="downloaded", message="ok")
    db.add(done)
    db.commit()
    assert "videos" not in client.get(f"/api/jobs/{done.id}").json()


def test_cards_fragment_renders_the_requested_cards_in_order():
    client, db, channel = make_client()
    one = add_video(db, channel, "one")
    two = add_video(db, channel, "two")

    response = client.get(f"/videos/cards?ids={two.id},{one.id},999&section=videos")

    assert response.status_code == 200
    html = response.text
    assert html.index("Titre two") < html.index("Titre one")
    assert "<html" not in html


def test_cancel_marks_a_running_channel_import_as_cancelled_and_done():
    client, db, channel = make_client()
    job = DownloadJob(channel_id=channel.id, status="running", message="Import en cours")
    db.add(job)
    db.commit()

    payload = client.post(f"/api/jobs/{job.id}/cancel").json()

    assert payload["status"] == "cancelled"
    assert payload["done"] is True
    assert client.get(f"/api/jobs/{job.id}").json()["done"] is True
    # A finished job is left as it is.
    finished = DownloadJob(channel_id=channel.id, status="metadata", message="ok")
    db.add(finished)
    db.commit()
    assert client.post(f"/api/jobs/{finished.id}/cancel").json()["status"] == "metadata"
    assert client.post("/api/jobs/99999/cancel").status_code == 404


def test_cards_carry_their_video_id_for_the_exploration_dedup():
    client, db, channel = make_client()
    video = add_video(db, channel, "one")

    assert f'data-video-id="{video.id}"' in get_channel_page(client, channel)


def test_a_downloaded_short_tile_plays_fullscreen_and_an_audio_only_one_opens_its_fiche():
    client, db, channel = make_client()
    played = add_video(db, channel, "vid", short=True, age_days=1)
    audio = add_video(
        db,
        channel,
        "aud",
        short=True,
        age_days=2,
        video_path=None,
        audio_path="/x/audio.m4a",
        media_type="audio",
    )

    html = get_channel_page(client, channel, "&section=shorts")

    assert f'data-short-play="/api/videos/{played.id}/video"' in html
    assert f'data-short-play="/api/videos/{audio.id}/video"' not in html
    assert html.count("data-short-play=") == 1
