"""The `/api` contract as a whole: typed replies, one error format, declared error codes."""

import ast
import inspect
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api
from app.db.base import *  # noqa: F403
from app.db.session import Base, get_db
from app.main import app
from app.models.video import Video

ROUTES = [route for module in api.MODULES for route in module.router.routes]
# Helpers of app/api/lookups.py: each answers 404 when the record is missing.
LOOKUPS_404 = {"fiche", "library_channel", "library_playlist", "playlist_item"}


def raised_codes(endpoint) -> set[int]:
    """The error codes a route's own code can answer: its HTTPExceptions and its lookups."""
    codes = set()
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", None))
        if name == "HTTPException":
            codes |= {
                kw.value.value
                for kw in node.keywords
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
            }
        elif name in LOOKUPS_404:
            codes.add(404)
    return codes


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(Video(yt_video_id="a", title="t", url="u", folder_path="f"))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: f"{','.join(r.methods)} {r.path}")
def test_each_route_declares_the_error_codes_it_answers(route):
    declared = {code for code in route.responses if int(code) >= 400 and int(code) != 422}

    assert declared == raised_codes(route.endpoint), (
        "add or remove codes in responses=error_responses(...)"
    )


def test_every_route_is_typed_and_every_error_uses_the_api_format():
    spec = app.openapi()
    for path, operations in spec["paths"].items():
        assert path.startswith("/api/"), f"{path}: HTML routes stay out of the schema"
        for method, operation in operations.items():
            success = [code for code in operation["responses"] if code.startswith("2")]
            assert success, f"{method} {path}"
            content = operation["responses"][success[0]].get("content", {})
            if success[0] != "204" and "text/csv" not in str(content):
                schema = content["application/json"]["schema"]
                assert "$ref" in str(schema) or "items" in schema, f"{method} {path}: untyped"
            for code, response in operation["responses"].items():
                if int(code) >= 400:
                    ref = response["content"]["application/json"]["schema"]["$ref"]
                    assert ref.endswith("/ErrorRead"), f"{method} {path} {code}"


def test_a_validation_error_answers_a_french_detail_and_its_fields(client):
    response = client.put("/api/videos/1/list-state", json={})
    page = client.get("/api/videos?page=abc")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Requête invalide : state : champ obligatoire.",
        "errors": [{"field": "state", "message": "champ obligatoire"}],
    }
    assert page.json()["detail"] == "Requête invalide : page : doit être un nombre entier."


def test_html_routes_keep_fastapi_validation_answer(client):
    response = client.post("/videos/1/rating", data={})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_html_routes_redirect_and_leave_json_to_the_api():
    """The page scripts call `/api`; a form route only serves the no-JS fallback. The iOS
    share shortcut is the one HTML route answering JSON, it cannot follow a redirect."""
    routes_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "routes"
    answering_json = {
        path.name
        for path in routes_dir.glob("*.py")
        if "JSONResponse(" in path.read_text(encoding="utf-8")
    }
    scripts = Path(__file__).resolve().parents[1] / "app"
    fetch_header = [
        str(path.relative_to(scripts))
        for path in [*scripts.glob("static/js/*.js"), *scripts.glob("templates/**/*.html")]
        if "X-Requested-With" in path.read_text(encoding="utf-8")
    ]

    assert answering_json == {"videos.py"}
    assert "def share_import_video" in (routes_dir / "videos.py").read_text(encoding="utf-8")
    assert fetch_header == []
