import pytest

from app.services.channels import scan_events, throttle


@pytest.fixture(autouse=True)
def no_scan_pauses(monkeypatch):
    """The pauses that keep a scan under YouTube's rate limits would only slow the tests down."""
    monkeypatch.setattr(throttle, "PAUSE_BETWEEN_IMPORTS", (0.0, 0.0))
    monkeypatch.setattr(throttle, "PAUSE_BETWEEN_CHANNELS", (0.0, 0.0))
    monkeypatch.setattr(throttle, "PAUSE_AFTER_LISTING_ONLY", (0.0, 0.0))


@pytest.fixture(autouse=True)
def empty_scan_events():
    scan_events.reset()
