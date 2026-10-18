"""The migrations form one chain: two PRs adding a revision on the same parent leave two heads on main."""

import re
from pathlib import Path

VERSIONS = sorted((Path(__file__).resolve().parent.parent / "alembic" / "versions").glob("*.py"))
REVISION = re.compile(r'^revision: str = "([^"]+)"', re.MULTILINE)
DOWN_REVISION = re.compile(r'^down_revision: str \| None = (?:"([^"]+)"|None)', re.MULTILINE)


def test_migrations_have_a_single_head():
    # Each PR passes `make ci` alone; once both are merged, `alembic upgrade head` (the container's CMD) fails with
    # "Multiple head revisions" and the deployed app never starts. Rebase the later PR onto main and renumber it.
    revisions, parents = set(), set()
    for path in VERSIONS:
        text = path.read_text(encoding="utf-8")
        revisions.add(REVISION.search(text).group(1))
        parent = DOWN_REVISION.search(text)
        assert parent, f"{path.name} declares no down_revision"
        if parent.group(1):
            parents.add(parent.group(1))
    assert not parents - revisions, (
        f"down_revision pointing at an unknown revision: {parents - revisions}"
    )
    assert len(revisions - parents) == 1, f"several migration heads: {sorted(revisions - parents)}"
