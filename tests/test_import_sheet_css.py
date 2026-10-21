"""CSS guards of the import sheet (docs/spec/11-interface-html.md, "Bouton d'import")."""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[1] / "front" / "static" / "css" / "tailwind.input.css"
).read_text()


def test_closed_sheet_is_out_of_the_layout():
    # Without it, ::details-content keeps the closed sheet laid out: no animation on reopening.
    assert re.search(
        r"\.import-fab:not\(\[open\]\) > \.import-backdrop,\s*"
        r"\.import-fab:not\(\[open\]\) > \.import-sheet\s*\{\s*display:\s*none;",
        CSS,
    )


def test_backdrop_paints_nothing():
    # iOS Safari tints the status bar from fixed elements at the top: a painted veil stayed grey there.
    for block in re.findall(r"\.import-backdrop\s*\{(.*?)\}", CSS, re.DOTALL):
        assert "background" not in block
        assert "animation" not in block
