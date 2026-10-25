"""One player at a time (docs/spec/08-medias-et-lecteurs.md, "Un seul lecteur a la fois")."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "front/static/js/app.js").read_text(encoding="utf-8")


def test_starting_a_media_pauses_the_others():
    start = APP_JS.index("function initSinglePlayback()")
    body = APP_JS[start : APP_JS.index("\n}\n", start)]
    # `play` does not bubble: only a capture listener sees every player's start,
    # including the playlist player's <video> and the mini player's <audio>.
    assert 'document.addEventListener("play"' in body
    assert "}, true);" in body
    assert "media !== started && !media.paused" in body
    assert "\ninitSinglePlayback();\n" in APP_JS
