import pytest

from back.services.ingest import scan_events, throttle
from back.services.videos import history


@pytest.fixture(autouse=True)
def no_scan_pauses(monkeypatch):
    """The pauses that keep a scan under YouTube's rate limits would only slow the tests down."""
    monkeypatch.setattr(throttle, "PAUSE_BETWEEN_IMPORTS", (0.0, 0.0))
    monkeypatch.setattr(throttle, "PAUSE_BETWEEN_CHANNELS", (0.0, 0.0))
    monkeypatch.setattr(throttle, "PAUSE_AFTER_LISTING_ONLY", (0.0, 0.0))


REAL_HISTORY_WINDOW_DAYS = history.HISTORY_WINDOW_DAYS


@pytest.fixture
def real_history_window_days(monkeypatch):
    """Puts the Historique's real window back (see `unbounded_history_window`); returns its days."""
    monkeypatch.setattr(history, "HISTORY_WINDOW_DAYS", REAL_HISTORY_WINDOW_DAYS)
    return REAL_HISTORY_WINDOW_DAYS


@pytest.fixture(autouse=True)
def unbounded_history_window(monkeypatch):
    """Tests date their playbacks on fixed days; the Historique's window counts back from the real
    clock, which would drop them once those days are old. `test_history_window.py` puts it back."""
    monkeypatch.setattr(history, "HISTORY_WINDOW_DAYS", 100_000)


@pytest.fixture(autouse=True)
def empty_scan_events():
    scan_events.reset()


@pytest.fixture(autouse=True)
def reset_front():
    yield
    from tests.site import reset_site

    reset_site()


@pytest.fixture
def front_client():
    """`front_client(db)`: the site (see `tests/site.py`) with the back serving `db`."""
    from back.db.session import get_db
    from back.main import app as back_app
    from tests.site import site_client

    def build(db):
        back_app.dependency_overrides[get_db] = lambda: db
        return site_client()

    yield build
    back_app.dependency_overrides.pop(get_db, None)
