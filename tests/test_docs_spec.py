"""Every spec file carries the frontmatter the Starlight site (docs-site/) needs."""

import json
import re
from pathlib import Path

import pytest

SPEC_DIR = Path(__file__).resolve().parent.parent / "docs" / "spec"
# ops/docs/ and monitoring/docs/ are the tools' own specs (ops/CLAUDE.md, monitoring/CLAUDE.md): same
# frontmatter rule, not published on the site.
OPS_SPEC_FILES = sorted(
    path
    for tool in ("ops", "monitoring")
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
    # The site renders the title itself and drops the markdown '# ' line, so they must not drift apart.
    match = re.search(r'^title: (".+")$', frontmatter(path), re.MULTILINE)
    assert match, f"{path.name}: frontmatter needs a quoted title"
    assert json.loads(match.group(1)) == first_heading(path)


def test_readme_is_the_site_home():
    assert re.search(r"^slug: index$", frontmatter(SPEC_DIR / "README.md"), re.MULTILINE)


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda p: p.name)
def test_file_name_is_sidebar_safe(path):
    # docs-site/astro.config.mjs builds the sidebar from these file names; one that does not slugify to itself breaks the build.
    assert path.name == "README.md" or re.fullmatch(r"[0-9]{2}-[a-z0-9-]+\.md", path.name), (
        f"{path.name}: spec file names must match NN-lowercase-words.md"
    )
