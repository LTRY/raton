"""Raton's introduction (docs/spec/11-interface-html.md, "Introduction de Raton")."""

import re
from pathlib import Path

from tests.test_front_skeleton import make_session

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "front" / "static" / "js" / "app.js").read_text()


def test_every_page_carries_the_hidden_introduction(front_client):
    page = front_client(make_session()).get("/raton/variations").text

    assert re.search(r'<div class="intro" data-intro [^>]*hidden>', page)
    arts = re.findall(r'<li data-art="([a-z_]+)">', page)
    assert arts, "the introduction has no line"
    for art in arts:
        assert (ROOT / "front" / "static" / "img" / "raton" / f"{art}.webp").is_file(), art


def test_screenshots_skip_the_introduction():
    # Otherwise every capture of scripts/screenshot.sh would show the introduction.
    key = re.search(r'const INTRO_SEEN_KEY = "([^"]+)";', JS).group(1)
    assert f'localStorage.setItem("{key}", "1")' in (ROOT / "scripts" / "screenshot.sh").read_text()
