"""Alembic revision ids must fit `alembic_version.version_num`, a VARCHAR(32) on PostgreSQL."""

import re
from pathlib import Path

import pytest

VERSIONS = sorted((Path(__file__).resolve().parent.parent / "alembic" / "versions").glob("*.py"))
REVISION = re.compile(r'^revision: str = "([^"]+)"', re.MULTILINE)


@pytest.mark.parametrize("path", VERSIONS, ids=lambda p: p.name)
def test_revision_id_fits_alembic_version_column(path):
    match = REVISION.search(path.read_text(encoding="utf-8"))
    assert match, f"{path.name} declares no revision id"
    assert len(match.group(1)) <= 32, f"{path.name}: revision id longer than 32 characters"
