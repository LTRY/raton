#!/usr/bin/env python3
"""Validate a pull request title against the rules of docs/spec/04-configuration-et-deploiement.md.

Usage: scripts/check_pr_title.py "<title>"      (exit 0 = valid, 1 = invalid, reasons on stderr)
"""

import re
import sys

TAGS = ("FRONT", "BACK", "DB", "CI", "DOCS")
MAX_SUMMARY = 72
TITLE_RE = re.compile(r"^((?:\[[A-Z]+\])+) (.+)$")
TYPE_PREFIX_RE = re.compile(
    r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style)(\(.+\))?!?:", re.I
)


def check(title: str) -> list[str]:
    match = TITLE_RE.match(title)
    if not match:
        return [
            "the title must be `[TAG] Summary` (tags glued together, one space, then the summary)"
        ]
    tags = re.findall(r"\[([A-Z]+)\]", match.group(1))
    summary = match.group(2)

    errors = []
    unknown = [t for t in tags if t not in TAGS]
    if unknown:
        errors.append(f"unknown tag(s) {unknown}; allowed: {', '.join(TAGS)}")
    if len(set(tags)) != len(tags):
        errors.append("a tag appears twice")
    if "FRONT" in tags and "BACK" in tags and tags.index("FRONT") > tags.index("BACK"):
        errors.append("front and back together are written `[FRONT][BACK]`, in that order")
    if len(summary) > MAX_SUMMARY:
        errors.append(f"the summary is {len(summary)} characters long, {MAX_SUMMARY} at most")
    if not summary[0].isupper():
        errors.append("the summary starts with a capital letter")
    if summary.endswith("."):
        errors.append("no trailing period")
    if TYPE_PREFIX_RE.match(summary):
        errors.append("no `feat:`/`fix:` type prefix; a fix starts its summary with `Fix`")
    if re.search(r"#\d+|session_", summary):
        errors.append("no PR number or session id in the title")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    errors = check(sys.argv[1])
    for error in errors:
        print(f"PR title: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
