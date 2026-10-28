from base64 import b64encode
from datetime import datetime

from monitoring import config as monitoring_config
from monitoring import render as monitoring_render
from monitoring import server as monitoring_server
from monitoring.review import Review


def test_no_token_means_an_open_page():
    assert monitoring_server.authorized(None, "")


def test_a_token_is_the_password_of_basic_auth():
    good = "Basic " + b64encode(b"anyone:secret").decode()
    bad = "Basic " + b64encode(b"anyone:nope").decode()

    assert monitoring_server.authorized(good, "secret")
    assert not monitoring_server.authorized(bad, "secret")
    assert not monitoring_server.authorized(None, "secret")
    assert not monitoring_server.authorized("Basic !!!", "secret")


def test_a_form_from_another_site_is_refused():
    assert monitoring_server.same_origin(None, "nas:8998")
    assert monitoring_server.same_origin("http://nas:8998", "nas:8998")
    assert not monitoring_server.same_origin("http://evil.example", "nas:8998")


def test_the_page_shows_the_review_card_and_escapes_the_project_name(monkeypatch):
    monkeypatch.setattr(
        monitoring_render,
        "CONFIG",
        monitoring_config.MonitoringConfig(project_name="A<b>'c"),
    )
    review = Review(
        id="2026-10-23-080000",
        started=datetime(2026, 10, 23, 8).isoformat(),
        trigger="scheduled",
        hours=24,
        ok=True,
        cost_usd=0.1,
        duration_ms=1,
        text="**Nominal**",
    )

    page = monitoring_render.render_page([review], review_busy=False)

    assert "A&lt;b&gt;&#x27;c" in page and "<b>" not in page
    assert "Revue des journaux" in page and "/reviews/2026-10-23-080000" in page
    assert 'http-equiv="refresh"' not in page


def test_the_page_refreshes_itself_while_a_review_runs():
    assert 'http-equiv="refresh"' in monitoring_render.render_page([], review_busy=True)
