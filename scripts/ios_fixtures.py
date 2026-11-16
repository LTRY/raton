"""The API answers the iOS app's unit tests decode (`ios/RatonTests/Fixtures/*.json`).

Run as `python -m scripts.ios_fixtures` to write them again, from the demo data
(`scripts/demo_seed.py`) on a throwaway database. They are the contract between the back and the
Swift models (`ios/Raton/Models.swift`): `tests/test_ios_fixtures.py` fails when an answer of the
API no longer has the shape of its fixture, and the app's `ModelDecodingTests` fail when a Swift
model cannot decode it. A change of the API that the app reads therefore shows up on both sides.
"""

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403  (registers every model on Base.metadata)
from back.db.session import Base, get_db
from back.main import app
from scripts.demo_seed import seed_demo

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "ios" / "RatonTests" / "Fixtures"

# Fixture name -> (method, path). The Swift model each one is decoded into is in
# `ios/RatonTests/ModelDecodingTests.swift`, under the same name.
CALLS = {
    "users": ("GET", "/api/users"),
    "library": ("GET", "/api/library?hide=none"),
    "library_channel": ("GET", "/api/library?channel_id=1&hide=none"),
    "video": ("GET", "/api/videos/1"),
    "channels": ("GET", "/api/channels?rated=false"),
    "channel": ("GET", "/api/channels/1"),
    "playlists": ("GET", "/api/playlists"),
    "playlist": ("GET", "/api/playlists/1"),
    "historique": ("GET", "/api/historique?page=1"),
    "settings": ("GET", "/api/settings"),
    "screen_time": ("GET", "/api/screen-time"),
    "categories": ("GET", "/api/categories"),
}


@contextmanager
def demo_client() -> Iterator[TestClient]:
    """The API on an in-memory database holding the demo data and one playlist of two fiches."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    with tempfile.TemporaryDirectory() as media_root:
        seed_demo(db, Path(media_root))
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            playlist = client.post("/api/playlists", json={"title": "Démo"}).json()
            for video_id in (1, 2):
                client.post(f"/api/playlists/{playlist['id']}/items", json={"video_id": video_id})
            yield client
        finally:
            app.dependency_overrides.pop(get_db, None)
            db.close()


def answers(client: TestClient) -> dict[str, object]:
    result = {}
    for name, (method, path) in CALLS.items():
        response = client.request(method, path)
        response.raise_for_status()
        result[name] = response.json()
    return result


def shape(value: object) -> object:
    """What a model decodes: the keys and the kind of each value, not the values themselves.
    A list is the set of the shapes of its items, so its length and order do not count."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = {json.dumps(shape(item), sort_keys=True) for item in value}
        return [json.loads(text) for text in sorted(shapes)]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    return "string"


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    with demo_client() as client:
        for name, answer in answers(client).items():
            path = FIXTURES_DIR / f"{name}.json"
            path.write_text(
                json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
