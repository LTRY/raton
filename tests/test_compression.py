"""Text responses are gzipped; media and image streams are left alone."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.testclient import TestClient

from back.core.compression import TextGZipMiddleware

app = FastAPI()
app.add_middleware(TextGZipMiddleware, minimum_size=1024)


@app.get("/page", response_class=HTMLResponse)
def page():
    return "<p>" + "bonjour " * 2000 + "</p>"


@app.get("/small", response_class=HTMLResponse)
def small():
    return "<p>ok</p>"


@app.get("/video")
def video():
    return Response(b"\x00" * 50_000, media_type="video/mp4")


@app.get("/image")
def image():
    return Response(b"\x00" * 50_000, media_type="image/jpeg")


@app.get("/json")
def data():
    return {"rows": ["bonjour"] * 2000}


client = TestClient(app)
GZIP = {"Accept-Encoding": "gzip"}


def test_html_and_json_are_gzipped_and_decode_to_the_same_content():
    for path in ("/page", "/json"):
        plain = client.get(path, headers={"Accept-Encoding": "identity"})
        packed = client.get(path, headers=GZIP)
        assert packed.headers["content-encoding"] == "gzip"
        assert int(packed.headers["content-length"]) < len(plain.content) / 5
        assert packed.content == plain.content  # httpx decodes it
        assert "content-encoding" not in plain.headers


def test_media_and_images_are_never_gzipped():
    for path in ("/video", "/image"):
        response = client.get(path, headers=GZIP)
        assert "content-encoding" not in response.headers
        assert len(response.content) == 50_000


def test_small_responses_are_left_as_they_are():
    assert "content-encoding" not in client.get("/small", headers=GZIP).headers


def test_the_real_app_installs_the_middleware():
    from back.main import app as real_app

    assert any(middleware.cls is TextGZipMiddleware for middleware in real_app.user_middleware)
