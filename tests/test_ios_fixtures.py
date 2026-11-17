import json

import pytest

from scripts.ios_fixtures import CALLS, FIXTURES_DIR, answers, demo_client, shape


@pytest.fixture(scope="module")
def fresh():
    with demo_client() as client:
        return answers(client)


@pytest.mark.parametrize("name", sorted(CALLS))
def test_api_answer_still_has_the_shape_the_ios_app_decodes(fresh, name):
    # The Swift models are tested against these files (`ModelDecodingTests`), which nothing in
    # `make ci` compiles. When the API changes what it answers, write the fixtures again
    # (`uv run python -m scripts.ios_fixtures`) and update `ios/Raton/Models.swift` with them.
    fixture = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))

    assert shape(fresh[name]) == shape(fixture)


def test_every_fixture_file_is_a_known_call():
    assert {path.stem for path in FIXTURES_DIR.glob("*.json")} == set(CALLS)
