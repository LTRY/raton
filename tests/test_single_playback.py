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


PLAYLIST_JS = (ROOT / "front/static/js/playlist-player.js").read_text(encoding="utf-8")
BASE = (ROOT / "front/templates/base.html").read_text(encoding="utf-8")


def test_playlist_audio_mode_plays_through_the_mini_player_queue():
    # Spec 08, "File d'une playlist": the bar shows the playlist's track and
    # playback goes on after leaving the page.
    assert "playQueue(" in APP_JS and "updateQueue(" in APP_JS
    assert "mini()?.playQueue(" in PLAYLIST_JS
    assert "mini().next()" in PLAYLIST_JS and "mini().previous()" in PLAYLIST_JS
    # A queued track ends: the mini player starts the next one by itself.
    assert "if (queue) nextInQueue();" in APP_JS
    assert 'data-mini-player-track="previous"' in BASE
    assert 'data-mini-player-track="next"' in BASE
