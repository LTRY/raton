"""The Jinja environment of the pages and the helpers templates call."""

import os

from fastapi.templating import Jinja2Templates

from front import cards, formatting
from front.config import FRONT_DIR

templates = Jinja2Templates(directory=FRONT_DIR / "templates")


def static_asset_version(relative_path: str) -> int:
    # Cache-buster for the static assets: StaticFiles sets no Cache-Control, so without it a phone
    # browser can keep an old app.js long after a deploy.
    try:
        return int(os.path.getmtime(FRONT_DIR / "static" / relative_path))
    except OSError:
        return 0


for helper in (
    static_asset_version,
    formatting.format_french_date,
    formatting.format_french_datetime,
    formatting.format_compact_duration,
    formatting.format_two_unit_duration,
    formatting.format_storage_bytes,
    formatting.format_video_file_size,
    formatting.format_subscribers,
    formatting.video_category_css_style,
    cards.badge_labels,
):
    templates.env.globals[helper.__name__] = helper
