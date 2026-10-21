import httpx
import pytest

from back.services.youtube.sponsorblock import fetch_sponsorblock_segments


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_fetch_sponsorblock_segments_returns_matching_categories(monkeypatch):
    def fake_get(url, params, timeout):
        assert url == "https://sponsor.ajay.app/api/skipSegments"
        assert params["videoID"] == "abc123"
        assert "sponsor" in params["categories"]
        return FakeResponse(
            200,
            [
                {"category": "sponsor", "segment": [42.0, 105.5], "UUID": "a"},
                {"category": "selfpromo", "segment": [580.0, 612.0], "UUID": "b"},
                {
                    "category": "preview",
                    "segment": [0.0, 10.0],
                    "UUID": "c",
                },  # not requested, must be dropped
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    segments = fetch_sponsorblock_segments("abc123", ["sponsor", "selfpromo"])

    assert segments == [
        {"category": "sponsor", "start_seconds": 42.0, "end_seconds": 105.5},
        {"category": "selfpromo", "start_seconds": 580.0, "end_seconds": 612.0},
    ]


def test_fetch_sponsorblock_segments_returns_empty_list_on_404(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, params, timeout: FakeResponse(404))

    assert fetch_sponsorblock_segments("abc123", ["sponsor"]) == []


def test_fetch_sponsorblock_segments_returns_empty_list_without_categories():
    assert fetch_sponsorblock_segments("abc123", []) == []


def test_fetch_sponsorblock_segments_raises_on_server_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, params, timeout: FakeResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_sponsorblock_segments("abc123", ["sponsor"])
