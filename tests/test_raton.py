"""Raton's home lines: catalogue consistency, the rotation, the home page and the test page."""

import json
import random
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.library_chat_conversation import LibraryChatConversation
from back.models.library_chat_message import LibraryChatMessage
from back.models.video import Video
from back.services.common.settings import get_setting, set_setting
from back.services.raton.picker import (
    active_scenarios,
    all_variations,
    art_files,
    draw_pool,
    line_art,
    line_key,
    line_text,
    missing_art,
    pick_next,
    stage_lines,
)
from back.services.raton.scenarios import (
    CATALOGUE,
    CONDITIONS,
    DEFAULT_SCENARIO,
    LONG_ABSENCE_DAYS,
    STAGE_ABSENCE,
    STAGE_DRAW,
    STAGE_GREETING,
    RatonContext,
)
from back.services.raton.visits import (
    RATON_SHOWN_KEY,
    home_context,
    record_visit,
    screen_time_today,
)
from tests.site import site_client

NOON = datetime(2026, 10, 10, 15, 0).astimezone()


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


def ctx(**overrides) -> RatonContext:
    values = {"now": NOON}
    values.update(overrides)
    return RatonContext(**values)


def ids(context: RatonContext) -> list[str]:
    """Ids of the scenarios that hold, over all stages, in catalogue order (default last)."""
    seen: list[str] = []
    for stage in (STAGE_ABSENCE, STAGE_GREETING, STAGE_DRAW):
        for scenario, _rank in stage_lines(context, stage):
            if scenario.id not in seen:
                seen.append(scenario.id)
    return seen


class FirstChoice:
    """Stands in for `random.Random`: always the first candidate, so a test reads in catalogue order."""

    def choice(self, seq):
        return seq[0]


def visit(context: RatonContext, loads: int, rng=None) -> list[tuple[str, int]]:
    """The (scenario id, rank) shown by `loads` successive page loads of one visit."""
    rng = rng or random.Random(7)
    shown: list[str] = []
    out: list[tuple[str, int]] = []
    for _ in range(loads):
        scenario, rank, shown = pick_next(context, shown, rng)
        out.append((scenario.id, rank))
    return out


def test_catalogue_ids_are_unique():
    all_ids = [scenario.id for scenario in CATALOGUE]
    assert len(all_ids) == len(set(all_ids))


def test_active_scenarios_match_conditions():
    assert {s.id for s in active_scenarios()} == set(CONDITIONS)


def test_every_active_scenario_has_a_stage_and_parked_ones_do_not_need_one():
    for scenario in [*active_scenarios(), DEFAULT_SCENARIO]:
        assert scenario.stage in (STAGE_ABSENCE, STAGE_GREETING, STAGE_DRAW), scenario.id


def test_every_scenario_has_at_least_one_line():
    for scenario in [*CATALOGUE, DEFAULT_SCENARIO]:
        assert scenario.lines, scenario.id


ART_DIR = Path(__file__).resolve().parents[1] / "front" / "static" / "img" / "raton"


def test_declared_art_files_exist():
    for scenario in [*CATALOGUE, DEFAULT_SCENARIO]:
        for name in art_files(scenario):
            assert (ART_DIR / name).is_file(), (scenario.id, name)


def test_missing_art_lists_the_parked_ideas():
    missing = {scenario.id for scenario in missing_art()}
    assert "clavier_ia" in missing
    assert "ecran_ferme" not in missing


def test_a_line_can_carry_its_own_drawing():
    nouveautes = next(s for s in CATALOGUE if s.id == "nouveautes")
    assert line_art(nouveautes, 0) == nouveautes.art
    assert line_art(nouveautes, 2) == "facteur.webp"
    assert line_text(nouveautes, 2) == "Le facteur est passé. Il a laissé du contenu."


def test_default_line_is_alone_when_nothing_applies():
    assert ids(ctx()) == ["defaut"]


def test_each_stage_collects_the_lines_of_its_holding_scenarios():
    context = ctx(limit_ratio=1.0, new_count=2, previous_visit=NOON - timedelta(days=5))
    assert ids(context) == ["longue_absence", "ecran_ferme", "nouveautes", "defaut"]
    nouveautes = next(s for s in active_scenarios() if s.id == "nouveautes")
    drawn = [
        (sc.id, rank) for sc, rank in stage_lines(context, STAGE_DRAW) if sc.id == "nouveautes"
    ]
    assert drawn == [("nouveautes", rank) for rank in range(len(nouveautes.lines))]


def test_closing_wins_the_draw_over_new_videos_and_the_default():
    pool = draw_pool(ctx(limit_ratio=1.2, new_count=4))
    assert {scenario.id for scenario, _ in pool} == {"ecran_ferme"}
    assert all(scenario.closing for scenario, _ in pool)
    assert {scenario.id for scenario, _ in draw_pool(ctx(limit_ratio=0.95, new_count=4))} == {
        "nouveautes",
        "defaut",
    }


def test_parked_scenarios_never_hold():
    lunch = datetime(2026, 10, 10, 13, 0).astimezone()
    late = datetime(2026, 10, 10, 22, 30).astimezone()
    parked = {"limite_proche", "quart_d_heure", "pause_midi", "tard"}
    for context in (
        ctx(limit_ratio=0.95, minutes_left=3),
        ctx(now=lunch, played_today_seconds=60),
        ctx(now=late),
    ):
        assert parked.isdisjoint(ids(context))


def test_long_absence_starts_at_two_days():
    assert LONG_ABSENCE_DAYS == 2
    assert ids(ctx(previous_visit=NOON - timedelta(days=3))) == ["longue_absence", "defaut"]
    assert ids(ctx(previous_visit=NOON - timedelta(days=2))) == ["longue_absence", "defaut"]
    assert ids(ctx(previous_visit=NOON - timedelta(days=1))) == ["defaut"]
    assert ids(ctx(new_count=3)) == ["nouveautes", "defaut"]


def test_visit_flow_is_absence_then_greeting_then_draw():
    morning = datetime(2026, 10, 10, 7, 30).astimezone()
    context = ctx(now=morning, new_count=1, previous_visit=morning - timedelta(days=4))
    stages = {s.id: s.stage for s in CATALOGUE}
    stages["defaut"] = DEFAULT_SCENARIO.stage
    flow = [stages[scenario_id] for scenario_id, _ in visit(context, 5)]
    assert flow == [STAGE_ABSENCE, STAGE_GREETING, STAGE_DRAW, STAGE_DRAW, STAGE_DRAW]


def test_visit_without_absence_opens_on_the_greeting():
    morning = datetime(2026, 10, 10, 7, 30).astimezone()
    assert visit(ctx(now=morning), 1)[0][0] == "matin_tot"


def test_visit_skips_the_greeting_when_no_time_slot_holds():
    # 15:00 and no play today: no greeting scenario, so the first load is already the draw.
    assert {scenario_id for scenario_id, _ in visit(ctx(new_count=1), 4)} <= {
        "nouveautes",
        "defaut",
    }


def test_greeting_is_shown_once_and_never_comes_back_in_the_draw():
    morning = datetime(2026, 10, 10, 7, 30).astimezone()
    shown = visit(ctx(now=morning, new_count=1), 12, random.Random(3))
    assert [scenario_id for scenario_id, _ in shown].count("matin_tot") == 1


def test_no_line_repeats_until_the_draw_is_exhausted():
    context = ctx(new_count=1)
    pool = len(draw_pool(context))
    first_round = visit(context, pool, random.Random(11))
    assert len(set(first_round)) == pool


def test_a_new_round_never_opens_on_the_line_just_shown():
    context = ctx(new_count=1)
    pool = len(draw_pool(context))
    for seed in range(20):
        run = visit(context, pool + 1, random.Random(seed))
        assert run[pool] != run[pool - 1]


def test_closing_visit_only_draws_closing_lines():
    context = ctx(limit_ratio=1.0, new_count=3)
    assert {scenario_id for scenario_id, _ in visit(context, 8)} == {"ecran_ferme"}


def test_unknown_lines_in_the_visit_state_are_forgotten():
    scenario, rank, shown = pick_next(ctx(), ["supprime:0"], FirstChoice())
    assert scenario.id == "defaut"
    assert shown == [line_key(scenario, rank)]


def test_midnight_greeting_runs_from_midnight_to_five():
    assert "minuit_passe" in ids(ctx(now=datetime(2026, 10, 10, 1, 0).astimezone()))
    assert "minuit_passe" not in ids(ctx(now=datetime(2026, 10, 10, 22, 0).astimezone()))
    assert "minuit_passe" not in ids(ctx(now=datetime(2026, 10, 10, 5, 0).astimezone()))


def test_new_videos_are_not_announced_late_at_night():
    late = datetime(2026, 10, 10, 23, 0).astimezone()
    assert ids(ctx(now=late, new_count=3)) == ["defaut"]


def test_morning_needs_a_first_visit_of_the_day():
    morning = datetime(2026, 10, 10, 7, 30).astimezone()
    assert ids(ctx(now=morning)) == ["matin_tot", "defaut"]
    seen_today = morning - timedelta(hours=1)
    assert ids(ctx(now=morning, previous_visit=seen_today)) == ["defaut"]
    assert ids(ctx(now=datetime(2026, 10, 10, 10, 0).astimezone())) == ["matin", "defaut"]


def test_visit_session_survives_a_refresh(db):
    start = datetime(2026, 10, 10, 9, 0).astimezone()
    assert record_visit(db, start - timedelta(days=20)) == (None, [])
    previous, _ = record_visit(db, start)
    assert previous is not None and (start - previous).days == 20
    # A refresh minutes later still reports the same previous visit.
    assert record_visit(db, start + timedelta(minutes=2))[0] == previous


def test_shown_lines_persist_within_a_visit_and_reset_on_a_new_one(db):
    start = datetime(2026, 10, 10, 9, 0).astimezone()
    record_visit(db, start)
    set_setting(db, RATON_SHOWN_KEY, json.dumps(["defaut:0"]))
    db.commit()
    # Less than SESSION_GAP since the last load: still the same visit.
    assert record_visit(db, start + timedelta(minutes=25))[1] == ["defaut:0"]
    # A long pause opens a new visit, which starts with nothing shown.
    assert record_visit(db, start + timedelta(hours=3))[1] == []
    assert get_setting(db, RATON_SHOWN_KEY, "") == "[]"


def test_home_context_survives_reloads_with_a_single_line_pool(db):
    default_line = line_text(DEFAULT_SCENARIO, 0)
    lines = [home_context(db, NOON)["scenario"]["line"] for _ in range(3)]
    assert lines == [default_line] * 3


def test_home_page_is_only_raton_and_the_chat(db):
    channel = Channel(name="A", url="https://youtube.com/@a", auto_metadata_enabled=True)
    db.add(channel)
    db.flush()
    db.add(
        Video(
            yt_video_id="r1",
            title="Une vidéo suivie",
            url="https://youtube.com/watch?v=r1",
            folder_path="/m/r1",
            video_path="/m/r1/v.mp4",
            is_new=True,
            channel_id=channel.id,
        )
    )
    db.commit()
    response = site_client().get("/")
    assert response.status_code == 200
    assert 'id="dashboard-chat"' in response.text
    assert "Une vidéo suivie" not in response.text
    assert "home-row" not in response.text


def chat_config(html):
    raw = html.split("data-chat-config='", 1)[1].split("'", 1)[0]
    return json.loads(raw.replace("&#39;", "'").replace("&amp;", "&"))["scopes"]["library"]


def test_home_opens_on_raton_and_a_discussion_from_its_address(db):
    older = LibraryChatConversation(title="Ancienne", updated_at=datetime(2026, 10, 1, tzinfo=UTC))
    latest = LibraryChatConversation(title="Récente", updated_at=datetime(2026, 10, 20, tzinfo=UTC))
    db.add_all([older, latest])
    db.flush()
    for conversation in (older, latest):
        db.add(LibraryChatMessage(conversation_id=conversation.id, role="user", content="Q ?"))
    db.commit()
    client = site_client()

    home = client.get("/").text
    opened = client.get(f"/?discussion={older.id}").text
    unknown = client.get("/?discussion=999")

    assert 'data-chat-empty="true"' in home
    assert 'data-chat-navigable="true"' in home
    assert "data-chat-drawer-toggle" in home
    assert chat_config(home)["conversationId"] is None
    assert [item["title"] for item in chat_config(home)["conversations"]] == [
        "Récente",
        "Ancienne",
    ]
    assert chat_config(opened)["conversationId"] == older.id
    assert 'data-chat-empty="false"' in opened
    assert unknown.status_code == 200
    assert chat_config(unknown.text)["conversationId"] is None


def test_home_announces_new_videos_with_its_button(db):
    channel = Channel(name="A", url="https://youtube.com/@a", auto_metadata_enabled=True)
    db.add(channel)
    db.flush()
    db.add(
        Video(
            yt_video_id="n1",
            title="N1",
            url="https://youtube.com/watch?v=n1",
            folder_path="/m/n1",
            is_new=True,
            channel_id=channel.id,
        )
    )
    db.commit()
    page = home_context(db, NOON, FirstChoice())
    assert page["scenario"]["line"] == "Il y a du nouveau, Chef."
    assert page["scenario"]["cta_href"] == "/dashboard/nouveautes"


def played_job(seconds: float, at: datetime, label: str = "vidéo") -> DownloadJob:
    payload = {
        "type": "playback",
        "action": "Lecture",
        "media_label": label,
        "position_seconds": seconds,
        "duration_seconds": 7200,
        "watched_seconds": seconds,
    }
    return DownloadJob(status="played", message=json.dumps(payload), created_at=at)


def test_screen_time_closes_at_the_daily_limit(db):
    set_setting(db, "screen_time_video_today_limit_minutes", "60")
    db.add(played_job(3600, NOON - timedelta(hours=1)))
    db.commit()
    ratio, kind, minutes_left, played = screen_time_today(db, NOON)
    assert (kind, round(ratio, 2), minutes_left, played) == ("video", 1.0, 0.0, 3600.0)
    page = home_context(db, NOON)
    assert page["scenario"]["id"] == "ecran_ferme"
    assert page["scenario"]["closing"] is True
    assert page["scenario"]["cta_href"] == "/dashboard/historique"


def test_minutes_left_uses_the_closest_limit_not_the_busiest_kind(db):
    set_setting(db, "screen_time_video_today_limit_minutes", "600")
    set_setting(db, "screen_time_music_today_limit_minutes", "30")
    db.add(played_job(400 * 60, NOON - timedelta(hours=1)))
    db.add(played_job(15 * 60, NOON - timedelta(hours=2), label="audio"))
    db.commit()
    ratio, kind, minutes_left, _ = screen_time_today(db, NOON)
    assert kind == "video"
    assert round(minutes_left) == 15


def test_new_count_ignores_channels_without_a_bell(db):
    followed = Channel(name="A", url="https://youtube.com/@a", auto_metadata_enabled=True)
    other = Channel(name="B", url="https://youtube.com/@b")
    db.add_all([followed, other])
    db.flush()
    for i, channel in enumerate((followed, other)):
        db.add(
            Video(
                yt_video_id=f"v{i}",
                title=f"V{i}",
                url=f"https://youtube.com/watch?v=v{i}",
                folder_path=f"/m/v{i}",
                is_new=True,
                channel_id=channel.id,
            )
        )
    db.commit()
    from back.services.raton.visits import build_context

    assert build_context(db, NOON).new_count == 1


def test_previous_visit_day_is_compared_in_the_current_timezone():
    now = datetime(2026, 10, 10, 8, 0, tzinfo=timezone(timedelta(hours=2)))
    # 22:30 UTC on the 9th is 00:30 on the 10th for `now`: same day, not a first visit.
    previous = datetime(2026, 10, 9, 22, 30, tzinfo=UTC)
    assert RatonContext(now=now, previous_visit=previous).first_visit_today is False


def test_variations_lists_every_active_line():
    groups = all_variations()
    expected = sum(len(s.lines) for s in active_scenarios()) + len(DEFAULT_SCENARIO.lines)
    assert sum(len(group["lines"]) for group in groups) == expected
    assert groups[0]["id"] == "longue_absence"
    assert groups[-1]["id"] == "defaut"


def test_variations_page_shows_everything_without_touching_the_visit(db):
    client = site_client()
    page = client.get("/raton/variations")
    assert page.status_code == 200
    assert "Je ferme boutique." in page.text
    assert "Voir l&#39;historique" in page.text or "Voir l'historique" in page.text
    assert "Limite de temps d&#39;écran atteinte aujourd&#39;hui" in page.text or (
        "Limite de temps d'écran atteinte aujourd'hui" in page.text
    )
    assert "raton-limit-bar" not in page.text
    # No line is a <h1>: the page's own title is the only one.
    assert page.text.count("<h1") == 1
    assert get_setting(db, RATON_SHOWN_KEY, "") == ""
