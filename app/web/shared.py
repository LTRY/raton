import json
import os
import random
from datetime import datetime
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import local_media_path
from app.models.channel import Channel
from app.models.video import Video
from app.services.common.settings_format import (
    parse_video_category_labels,
    video_category_css_style,
)
from app.services.videos.filters import video_category_labels

templates = Jinja2Templates(directory="app/templates")

LIBRARY_PAGE_SIZE = 50

FRENCH_WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
FRENCH_MONTHS_ABBR = [
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
]


def format_french_date(value: datetime) -> str:
    return f"{FRENCH_WEEKDAYS[value.weekday()]}. {value.day:02d} {FRENCH_MONTHS_ABBR[value.month - 1]} {value.year}"


def format_french_datetime(value: datetime) -> str:
    return f"{format_french_date(value)} {value:%H:%M}"


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def wants_json(request: Request | None) -> bool:
    # Set by the app.js fetch calls that update the page in place: a form
    # route answers them in JSON and keeps its redirect for plain submissions.
    return request is not None and request.headers.get("x-requested-with") == "fetch"


def internal_return_path(path: str, fallback: str = "/videos") -> str:
    if not path.startswith("/") or path.startswith("//"):
        return fallback
    return path


def append_query(path: str, params: dict[str, str]) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}{urlencode(params)}"


def current_request_path(request: Request, exclude: tuple[str, ...] = ()) -> str:
    path = request.url.path
    if exclude:
        query = urlencode(
            [
                (key, value)
                for key, value in request.query_params.multi_items()
                if key not in exclude
            ]
        )
        return f"{path}?{query}" if query else path
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path


def paginate(items: list, page: int, page_size: int = LIBRARY_PAGE_SIZE) -> tuple[list, int, int]:
    total_pages = max(1, -(-len(items) // page_size))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    return items[start : start + page_size], page, total_pages


def page_href_builder(request: Request, exclude: tuple[str, ...] = ()):
    def page_href(page: int) -> str:
        params = [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key != "page" and key not in exclude
        ]
        if page > 1:
            params.append(("page", str(page)))
        query = urlencode(params)
        return f"{request.url.path}?{query}" if query else request.url.path

    return page_href


def form_list_values(value: list[str] | None) -> list[str]:
    return value if isinstance(value, list) else []


def form_text_value(value: str | None) -> str:
    return value if isinstance(value, str) else ""


def channel_category_labels(channel: Channel) -> list[str]:
    return parse_video_category_labels(getattr(channel, "category_labels", None))


def video_metadata(video: Video) -> dict:
    if not video.metadata_path:
        return {}
    path = local_media_path(video.metadata_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return {}
    return data if isinstance(data, dict) else {}


def video_has_notes(video: Video) -> bool:
    if not video.transcript_path:
        return False
    return local_media_path(video.transcript_path).with_name("transcript.notes.txt").is_file()


def video_asset_labels(video: Video) -> list[dict[str, str]]:
    labels = []
    if getattr(video, "is_new", False):
        labels.append({"text": "Nouveau", "kind": "new"})
    if video.audio_path:
        labels.append({"text": "Audio", "kind": "audio"})
    if video.video_path:
        labels.append({"text": "Vidéo", "kind": "video"})
    if video.metadata_path or video.media_type == "metadata":
        labels.append({"text": "Métadonnées", "kind": "metadata"})
    if video.transcript_path:
        labels.append({"text": "Transcript", "kind": "transcript"})
    if video_has_notes(video):
        labels.append({"text": "Notes", "kind": "notes"})
    if video.imported_via_form:
        labels.append({"text": "Manuelle", "kind": "imported"})
    return labels


def category_style_map(label_styles: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {style["label"]: style for style in label_styles}


def static_asset_version(relative_path: str) -> int:
    # Cache-buster pour les assets statiques (JS/CSS) : StaticFiles ne pose pas
    # de Cache-Control, donc sans ce paramètre, un navigateur mobile peut garder
    # en cache une version obsolète bien après un déploiement.
    try:
        return int(os.path.getmtime(os.path.join("app/static", relative_path)))
    except OSError:
        return 0


# Shown under the raccoon when a channel has no card; one is drawn per render.
CHANNEL_EMPTY_MESSAGES = (
    "Chou blanc",
    "Le frigo est vide",
    "J’ai fouillé partout. Rien",
    "Tu as tout vu ! Reviens plus tard",
    "Je monte la garde, mais il ne se passe rien.",
    "Hmm. Suspect, tout ce vide.",
    "Rien ici. Pour l’instant.",
)


def random_channel_empty_message() -> str:
    return random.choice(CHANNEL_EMPTY_MESSAGES)


def install_template_globals(jinja_templates: Jinja2Templates) -> None:
    jinja_templates.env.globals["video_asset_labels"] = video_asset_labels
    jinja_templates.env.globals["video_category_labels"] = video_category_labels
    jinja_templates.env.globals["channel_category_labels"] = channel_category_labels
    jinja_templates.env.globals["video_category_css_style"] = video_category_css_style
    jinja_templates.env.globals["format_french_date"] = format_french_date
    jinja_templates.env.globals["format_french_datetime"] = format_french_datetime
    jinja_templates.env.globals["static_asset_version"] = static_asset_version
    jinja_templates.env.globals["random_channel_empty_message"] = random_channel_empty_message


install_template_globals(templates)
