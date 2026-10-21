import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[1] / "front" / "static" / "css" / "tailwind.input.css"
).read_text()
JS = (Path(__file__).resolve().parents[1] / "front" / "static" / "js" / "app.js").read_text()


def test_glass_tokens_are_defined_once_on_root():
    for name in (
        "--glass-fill",
        "--glass-fill-strong",
        "--glass-rim",
        "--glass-highlight",
        "--glass-blur",
        "--glass-blur-layer",
        "--glass-saturate",
    ):
        assert f"  {name}:" in CSS, name


def test_glass_blur_is_not_duplicated_as_literals():
    # The shared recipe lives in the variables; a literal would drift from them.
    assert "blur(24px) saturate(180%)" not in CSS
    assert "blur(22px) saturate(180%)" not in CSS


def test_lg_class_blurs_only_under_supports():
    start = CSS.index("\n.lg {")
    base = CSS[start : CSS.index("}", start)]
    assert "backdrop-filter" not in base
    assert "overflow" not in base
    assert "position" not in base
    assert ":where(.lg)" in CSS


def test_ambient_ground_is_hidden_in_print():
    assert "@media print" in CSS[CSS.index("body::before {") :]


def test_ambient_ground_is_flat_cream_on_phones():
    # Safari tints its status strip with the root background / theme-color: on a
    # phone the page must be the same flat cream, so no halos under 800px.
    tail = CSS[CSS.index("body::before {") :]
    assert "@media print, (max-width: 800px)" in tail


def test_theme_color_matches_the_page_background():
    base = (Path(__file__).resolve().parents[1] / "front" / "templates" / "base.html").read_text()
    bg = re.search(r"--color-bg:\s*(#[0-9a-fA-F]{6})", CSS).group(1)
    meta = re.search(
        r'<meta name="theme-color" content="(#[0-9a-fA-F]{6})" media="\(max-width: 800px\)">', base
    )
    assert meta, "theme-color must be limited to phones, where the background is flat"
    assert meta.group(1).lower() == bg.lower()


def test_ambient_ground_is_fixed_and_inert():
    start = CSS.index("body::before {")
    block = CSS[start : CSS.index("}", start)]
    assert "position: fixed" in block
    assert "pointer-events: none" in block
    assert "z-index: -1" in block


def test_glass_light_hook_is_wired():
    assert "[data-glass-light]" in JS
    assert "glassLightBound" in JS


def test_topbar_and_everyday_controls_use_the_glass_class():
    root = Path(__file__).resolve().parents[1] / "front" / "templates"
    assert '<header class="topbar lg">' in (root / "base.html").read_text()
    macros = (root / "_macros.html").read_text()
    start = macros.index("{% macro library_subnav")
    assert macros[start : macros.index("{% endmacro %}", start)].count('class="lg"') == 4
    for name in ("stats.html", "rag_dashboard.html", "settings.html", "_macros.html"):
        text = (root / name).read_text()
        assert 'class="button-link secondary"' not in text, name


def test_topbar_is_sticky_and_drops_its_blur_while_the_menu_is_open():
    start = CSS.index("/* Desktop top bar")
    block = CSS[start : CSS.index("/* An open library menu", start)]
    assert "position: sticky" in block
    assert ".topbar:has(.nav-library-menu[open])" in CSS


def test_cards_get_glass_look_without_blur():
    start = CSS.index("/* Cards: the glass look without the blur.")
    block = CSS[start : CSS.index("@media print", start)]
    assert ".dashboard-media-row {" in block
    assert "backdrop-filter" not in block


def test_settings_save_bar_uses_the_glass_class():
    root = Path(__file__).resolve().parents[1] / "front" / "templates"
    assert 'class="settings-actions lg"' in (root / "settings.html").read_text()


def test_slate_and_legacy_blue_are_gone_outside_the_rating_metals():
    kept = []
    section = ""
    for line in CSS.splitlines():
        if line.rstrip().endswith("{") and not line.strip().startswith("@"):
            section = line.strip()
        lowered = line.lower()
        if any(
            value in lowered
            for value in (
                "#2563a7",
                "#64748b",
                "#475569",
                "#d9dee5",
                "#e5e9ef",
                "#334155",
                "#0f172a",
            )
        ):
            if line.strip().startswith("/*"):
                continue
            kept.append((section, line.strip()))
    # The metal gradients of the rating tiers are the only place the slate palette still lives.
    assert all("rating-" in section for section, _ in kept), kept


def test_panels_get_the_blur_free_glass_look():
    start = CSS.index("/* Panels and form blocks")
    block = CSS[start : CSS.index("@media print", start)]
    assert ".settings-card," in block and ".filters-form," in block
    assert "backdrop-filter" not in block


def test_floating_layers_read_the_shared_glass_variables():
    start = CSS.index("/* Liquid glass, floating layers")
    block = CSS[start : CSS.index("/* `.lg`: the liquid-glass recipe", start)]
    assert "blur(22px)" not in block and "saturate(160%)" not in block
    assert "rgba(255, 255, 255, 0.92)" not in block
    assert "var(--glass-smoke)" in block


# Colours: a hex literal outside a custom-property definition is a colour that has no name yet.
# The count may only go down; when a rule moves onto a token, lower the baseline.
# What is left on purpose: the metal gradients of the rating tiers, the category and asset-label
# palettes, the player and the chart series.
HEX_LITERAL_LINES_BASELINE = 74


def _lines_with_hex_literals():
    import re

    declaration = re.compile(r"^\s*--[a-zA-Z0-9-]+\s*:")
    literal = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")
    return [
        line.strip()
        for line in CSS.splitlines()
        if not declaration.match(line)
        and not line.strip().startswith(("/*", "*"))
        and literal.search(line)
    ]


def test_hex_literals_do_not_grow():
    lines = _lines_with_hex_literals()
    assert len(lines) <= HEX_LITERAL_LINES_BASELINE, (
        f"{len(lines)} lines use a hex literal (baseline {HEX_LITERAL_LINES_BASELINE}): "
        "give the colour a token in :root / @theme and use var(--...)"
    )


def test_white_and_black_are_tokens():
    # Plain white and black are `--color-white` / `--color-black`, never typed again.
    for line in _lines_with_hex_literals():
        assert not re.search(r"#(?:ffffff|fff|000)(?![0-9a-fA-F])", line, re.IGNORECASE), line


def test_radii_use_the_scale():
    import re

    allowed = {"0", "1px", "2px", "3px", "4px", "5px", "50%", "inherit"}
    for match in re.finditer(r"^\s*border-radius: ([^;]+);", CSS, flags=re.MULTILINE):
        value = match.group(1).strip()
        assert value in allowed or "var(" in value or " " in value, f"border-radius: {value}"
