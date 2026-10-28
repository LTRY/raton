"""Users: `/api/users`, the user a request acts for, and the user menu of the front."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base, get_db
from back.main import app
from back.models.channel import Channel
from back.models.library_chat_conversation import LibraryChatConversation
from back.models.playlist import Playlist
from back.models.user import User, UserVideo
from back.models.video import Video
from back.services.jobs.llm_requests import queue_library_question
from tests.site import site_client
from tests.users import add_user, set_video_state, user_id


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


@pytest.fixture
def api():
    return TestClient(app)


def test_an_empty_db_gets_a_first_user_and_requests_act_for_it(api, db):
    listed = api.get("/api/users").json()

    assert listed == {"users": [{"id": 1, "name": "Moi"}], "current_user_id": 1}


def test_a_request_names_its_user_by_header_or_cookie_else_the_oldest(api, db):
    other = add_user(db, "Invité")

    by_header = api.get("/api/users", headers={"X-Raton-User": str(other.id)}).json()
    api.cookies.set("raton_user", str(other.id))
    by_cookie = api.get("/api/users").json()
    api.cookies.set("raton_user", "999")
    deleted = api.get("/api/users").json()
    api.cookies.set("raton_user", "pas-un-id")
    garbage = api.get("/api/users").json()

    assert by_header["current_user_id"] == other.id
    assert by_cookie["current_user_id"] == other.id
    # A deleted or unreadable user falls back to the oldest one.
    assert deleted["current_user_id"] == garbage["current_user_id"] == user_id(db)


def test_adding_and_renaming_check_the_name(api, db):
    user_id(db)

    created = api.post("/api/users", json={"name": "  Camille   B "})
    taken = api.post("/api/users", json={"name": "camille b"})
    blank = api.post("/api/users", json={"name": "   "})
    too_long = api.post("/api/users", json={"name": "x" * 41})
    renamed = api.put(f"/api/users/{created.json()['id']}", json={"name": "Cam"})
    clash = api.put(f"/api/users/{created.json()['id']}", json={"name": "MOI"})
    unknown = api.put("/api/users/999", json={"name": "Personne"})

    assert (created.status_code, created.json()["name"]) == (201, "Camille B")
    assert (taken.status_code, taken.json()) == (
        400,
        {"detail": "Un utilisateur porte déjà ce nom."},
    )
    assert blank.json() == {"detail": "Le nom de l'utilisateur est obligatoire."}
    assert too_long.json() == {"detail": "Le nom ne doit pas dépasser 40 caractères."}
    assert renamed.json()["name"] == "Cam"
    assert clash.status_code == 400
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "Utilisateur introuvable."})


def test_deleting_a_user_deletes_what_was_theirs_and_keeps_the_fiches(api, db):
    other = add_user(db, "Invité")
    channel = Channel(url="https://youtube.com/@c", name="C")
    video = Video(yt_video_id="v", title="V", url="https://youtube.com/watch?v=v", folder_path="/v")
    db.add_all([channel, video])
    db.commit()
    set_video_state(db, video, other.id, rating=5)
    db.add(Playlist(user_id=other.id, title="La sienne", source="manual"))
    db.add(LibraryChatConversation(user_id=other.id, title="Sa discussion"))
    db.commit()

    deleted = api.delete(f"/api/users/{other.id}")
    last = api.delete(f"/api/users/{user_id(db)}")

    assert deleted.status_code == 204
    assert db.query(User).count() == 1
    assert db.query(UserVideo).count() == 0
    assert db.query(Playlist).count() == 0
    assert db.query(LibraryChatConversation).count() == 0
    assert db.query(Video).count() == 1
    assert (last.status_code, last.json()) == (
        409,
        {"detail": "Impossible de supprimer le dernier utilisateur."},
    )


def test_the_user_settings_are_on_the_settings_page_not_in_the_home_drawer(db):
    user_id(db)
    add_user(db, "Invité")
    site = site_client()

    assert "/user" not in site.get("/").text.replace("/users", "")
    page = site.get("/settings").text
    # The user part comes first and is not admin; the admin part is, hidden on a phone.
    assert page.index('id="switch"') < page.index('class="settings-form settings-admin"')
    assert 'id="switch"' not in page[page.index('class="settings-form settings-admin"') :]


def test_the_settings_page_switches_renames_and_sets_ratons_language(db):
    user_id(db)
    add_user(db, "Invité")
    site = site_client()

    page = site.get("/settings").text
    assert page.count('action="/users/switch"') == 2
    assert 'aria-current="true" disabled' in page
    assert 'class="chat-user-add" method="post" action="/users"' in page
    assert f'action="/users/{user_id(db)}/rename"' in page

    renamed = site.post(
        f"/users/{user_id(db)}/rename",
        data={"name": "Léa", "next": "/settings"},
        follow_redirects=False,
    )
    assert renamed.headers["location"].startswith("/settings?")
    saved = site.post(
        "/user", data={"raton_address": "tu", "raton_nickname": " Chef "}, follow_redirects=False
    )
    assert saved.headers["location"].startswith("/settings?")
    page = site.get("/settings").text
    assert "<h2>Léa</h2>" in page
    assert 'value="tu" checked' in page
    assert 'value="Chef"' in page


def test_the_settings_page_sets_the_screen_time_limits(db):
    user_id(db)
    site = site_client()

    assert 'name="screen_time_video_today"' in site.get("/settings").text
    saved = site.post(
        "/user",
        data={
            "screen_time_video_today": "45",
            "screen_time_short_today": "5",
            "screen_time_podcast_today": "90",
            "screen_time_music_today": "0",
        },
        follow_redirects=False,
    )

    assert saved.headers["location"].startswith("/settings?")
    limits = TestClient(app).get("/api/settings").json()["screen_time_limits"]
    assert {kind: limits[kind]["today"] for kind in limits} == {
        "video": 45,
        "short": 5,
        "podcast": 90,
        "music": 1,
    }


def test_ratons_language_is_each_users_own_and_reaches_the_library_chat(db):
    other = add_user(db, "Invité")
    api = TestClient(app)

    api.put("/api/settings", json={"raton_address": "tu", "raton_nickname": "Chef"})

    assert api.get("/api/settings").json()["raton_language"] == {
        "address": "tu",
        "nickname": "Chef",
    }
    theirs = api.get("/api/settings", headers={"X-Raton-User": str(other.id)}).json()
    assert theirs["raton_language"] == {"address": "vous", "nickname": ""}
    assert api.put("/api/settings", json={"raton_nickname": "x" * 41}).status_code == 400
    assert api.put("/api/settings", json={"raton_address": "toi"}).status_code == 422

    job = queue_library_question(db, user_id(db), "Quoi de neuf ?", None)
    assert "Tutoie l'utilisateur. Appelle-le « Chef »" in json.loads(job.prompt)["system"]


def test_switching_user_sets_the_cookie_and_every_page_then_acts_for_them(db):
    user_id(db)
    other = add_user(db, "Invité")
    db.add(Playlist(user_id=other.id, title="Playlist de Léa", source="manual"))
    db.commit()
    client = site_client()

    before = client.get("/playlists").text
    switched = client.post("/users/switch", data={"user_id": other.id}, follow_redirects=False)
    # The page's own `/api` calls carry the user (X-Raton-User), and so do the relayed ones.
    after = client.get("/playlists").text
    relayed = client.get("/api/users").json()

    assert "Playlist de Léa" not in before
    assert switched.status_code == 303
    assert switched.headers["location"].startswith("/?message=Bonjour+Invit")
    assert f"raton_user={other.id}" in switched.headers["set-cookie"]
    assert "Playlist de Léa" in after
    assert relayed["current_user_id"] == other.id
    assert f'<meta name="raton-user" content="{other.id}">' in after


def test_adding_a_user_from_the_menu_switches_to_them(db):
    user_id(db)
    client = site_client()

    added = client.post("/users", data={"name": "Léa"}, follow_redirects=False)
    refused = client.post("/users", data={"name": "moi"}, follow_redirects=False)

    lea = db.query(User).filter_by(name="Léa").one()
    assert f"raton_user={lea.id}" in added.headers["set-cookie"]
    assert "level=error" in refused.headers["location"]
    assert "set-cookie" not in refused.headers


def test_the_settings_page_offers_the_deletion_and_deleting_oneself_goes_back_to_the_default(db):
    user_id(db)
    other = add_user(db, "Invité")
    client = site_client()
    client.cookies.set("raton_user", str(other.id))

    page = client.get("/settings").text
    deleted = client.post(f"/users/{other.id}/delete", follow_redirects=False)

    assert f'action="/users/{other.id}/delete"' in page and 'action="/users/1/delete"' in page
    assert deleted.headers["location"].startswith("/settings?message=")
    assert 'raton_user=""' in deleted.headers["set-cookie"]
