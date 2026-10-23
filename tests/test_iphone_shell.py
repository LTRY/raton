"""iPhone integration of the pages (docs/spec/11-interface-html.md, "Base" and
"Cibles tactiles"; docs/spec/08-medias-et-lecteurs.md, "Ecran verrouille")."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "front/templates/base.html").read_text(encoding="utf-8")
CSS = (ROOT / "front/static/css/tailwind.input.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "front/static/js/app.js").read_text(encoding="utf-8")
PLAYLIST_JS = (ROOT / "front/static/js/playlist-player.js").read_text(encoding="utf-8")


def test_viewport_covers_the_screen_so_safe_area_insets_apply():
    # Without viewport-fit=cover Safari reports every env(safe-area-inset-*) as 0.
    assert re.search(r'<meta name="viewport" content="[^"]*viewport-fit=cover', BASE)
    assert "env(safe-area-inset-bottom" in CSS


def test_home_screen_manifest_opens_standalone():
    assert '<link rel="manifest" href="/static/manifest.webmanifest">' in BASE
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="default">' in BASE
    manifest = json.loads((ROOT / "front/static/manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    bg = re.search(r"--color-bg:\s*(#[0-9a-fA-F]{6})", CSS).group(1).lower()
    assert manifest["background_color"].lower() == bg
    assert manifest["theme_color"].lower() == bg
    for icon in manifest["icons"]:
        assert (ROOT / "front" / icon["src"].lstrip("/")).is_file()


def test_touch_target_block_comes_last():
    # Same specificity as the page rules: the block only wins from the end of the file.
    start = CSS.rindex("@media (pointer: coarse)")
    block = CSS[start:]
    assert ".chip3" in block
    assert ".rating-star::after" in block
    assert CSS.rstrip().endswith("}")
    assert "@media" not in block[1:]


def test_players_claim_the_media_session():
    assert "navigator.mediaSession" in APP_JS
    # Mini-player, page players (bindResumableMedia) and the playlist player.
    assert APP_JS.count("claimMediaSession(") >= 3
    assert "releaseMediaSession(audio)" in APP_JS
    assert "ratonClaimMediaSession" in PLAYLIST_JS
    assert "{ previous: goPrevious, next: goNext }" in PLAYLIST_JS
