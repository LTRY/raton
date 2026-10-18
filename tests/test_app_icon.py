"""The home-screen icon declared in base.html exists and is iOS-compatible."""

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_base_template_declares_apple_touch_icon():
    html = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="/static/img/apple-touch-icon.png"' in html
    assert 'rel="icon"' in html


def test_apple_touch_icon_is_180px_png():
    data = (ROOT / "app/static/img/apple-touch-icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (180, 180)
