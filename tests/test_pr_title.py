import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_pr_title", Path(__file__).parent.parent / "scripts" / "check_pr_title.py"
)
check_pr_title = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_pr_title)


@pytest.mark.parametrize(
    "title",
    [
        "[FRONT] Stats: link channel names to their channel page",
        "[FRONT][BACK] Fix scan skipping shorts",
        "[BACK][DB] Add the playlist position column",
        "[FRONT][BACK][DB] Add the playlist position",
        "[DOCS] Clarify the glossary",
        "[OPS] Move the previews page into ops/",
        "[OPS][MONITORING] Split the log review out of ops/",
        "[IOS] Add the native iOS app: server URL, Nouveautés, player",
        "[BACK][IOS] Add a field the iOS app reads",
        "[CI] " + "A" * 72,
    ],
)
def test_valid_titles(title):
    assert check_pr_title.check(title) == []


@pytest.mark.parametrize(
    "title",
    [
        "Add a thing",
        "[FRONT]Add a thing",
        "[FRONT] [BACK] Add a thing",
        "[WEB] Add a thing",
        "[BACK][BACK] Add a thing",
        "[BACK][FRONT] Add a thing",
        "[BACK] add a thing",
        "[BACK] Add a thing.",
        "[BACK] fix: scan skipping shorts",
        "[BACK] Add a thing (#12)",
        "[CI] " + "A" * 73,
    ],
)
def test_invalid_titles(title):
    assert check_pr_title.check(title) != []
