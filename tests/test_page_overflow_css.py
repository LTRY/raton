"""The last-resort net of the "no horizontal page scroll on phones" rule (docs/spec/11-interface-html.md, "Base")."""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[1] / "front" / "static" / "css" / "tailwind.input.css"
).read_text()


def test_html_and_body_clip_horizontal_overflow():
    # `clip`, not `hidden`: `hidden` turns <body> into a scroll container and breaks `position: sticky`.
    match = re.search(r"^html,\s*body\s*\{(.*?)\}", CSS, re.MULTILINE | re.DOTALL)
    assert match, "no `html, body` rule in tailwind.input.css"
    assert re.search(r"overflow-x:\s*clip\s*;", match.group(1))


def test_page_fields_are_16px_on_touch_screens():
    # Below 16px, iOS Safari zooms into the page when the search field or the sort gets the focus.
    match = re.search(r"@media \(pointer: coarse\) \{(.*?)\n\}", CSS, re.DOTALL)
    assert match, "no `@media (pointer: coarse)` block in tailwind.input.css"
    rule = re.search(r"\.page-search input,\s*\.page-sort select\s*\{([^}]*)\}", match.group(1))
    assert rule and re.search(r"font-size:\s*16px\s*;", rule.group(1))
