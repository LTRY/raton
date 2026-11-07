"""Every spec file carries a frontmatter `title` equal to its first heading."""

import json
import re
from pathlib import Path

import pytest

SPEC_DIR = Path(__file__).resolve().parent.parent / "docs" / "spec"
# ops/docs/, monitoring/docs/ and ios/docs/ are the units' own specs (ops/CLAUDE.md, monitoring/CLAUDE.md): same
# frontmatter rule.
OPS_SPEC_FILES = sorted(
    path
    for tool in ("ops", "monitoring", "ios")
    for path in (SPEC_DIR.parent.parent / tool / "docs").glob("*.md")
)
SPEC_FILES = sorted(SPEC_DIR.glob("*.md"))
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def frontmatter(path: Path) -> str:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def first_heading(path: Path) -> str:
    match = re.search(r"^# (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{path.name} has no '# ' heading"
    return match.group(1).strip()


def test_spec_files_are_found():
    assert len(SPEC_FILES) >= 19


@pytest.mark.parametrize("path", SPEC_FILES + OPS_SPEC_FILES, ids=lambda p: p.name)
def test_title_matches_first_heading(path):
    match = re.search(r'^title: (".+")$', frontmatter(path), re.MULTILINE)
    assert match, f"{path.name}: frontmatter needs a quoted title"
    assert json.loads(match.group(1)) == first_heading(path)
