import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.same_origin import SameOriginMiddleware


def make_client(trusted=frozenset()):
    app = FastAPI()
    app.add_middleware(SameOriginMiddleware, trusted_hosts=trusted)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/write")
    def write():
        return {"ok": True}

    return TestClient(app, base_url="http://raton.lan:8000")


def test_reads_are_never_blocked():
    client = make_client()
    assert client.get("/ping", headers={"Origin": "https://evil.example"}).status_code == 200


def test_write_without_browser_headers_passes():
    assert make_client().post("/write").status_code == 200


def test_write_from_same_origin_passes():
    client = make_client()
    assert client.post("/write", headers={"Origin": "http://raton.lan:8000"}).status_code == 200
    referer = {"Referer": "http://raton.lan:8000/videos/1"}
    assert client.post("/write", headers=referer).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "http://raton.lan:9999"},
        {"Origin": "null"},
        {"Referer": "https://evil.example/page"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "same-origin", "Origin": "https://evil.example"},
    ],
)
def test_cross_site_write_is_refused(headers):
    assert make_client().post("/write", headers=headers).status_code == 403


def test_fetch_metadata_same_origin_passes():
    client = make_client()
    assert client.post("/write", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_trusted_host_is_accepted_behind_a_proxy():
    client = make_client(frozenset({"raton.example.org"}))
    assert client.post("/write", headers={"Origin": "https://raton.example.org"}).status_code == 200
