"""Request helpers of the page routes: current path, page links, redirects with a message."""

from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def internal_return_path(path: str, fallback: str = "/videos") -> str:
    """A form's `next`: only a path of this site, never another host (`//evil`)."""
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


# The two-button selector of a list: what each choice leaves out (`hide`, decided by the API).
LIST_HIDE_OPTIONS = (
    ("none", "Tout voir"),
    ("watched_hidden", "Masquer les déjà vues et les indésirées"),
)


def list_hide_selector(request: Request, current: str) -> dict:
    """The links of the selector: this page with `hide` set, back on its first page since the
    number of rows changes. `drop_states` are the card states the page removes on the spot."""
    params = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in ("hide", "page")
    ]
    options = [
        {
            "value": value,
            "label": label,
            "active": value == current,
            "href": f"{request.url.path}?{urlencode([*params, ('hide', value)])}",
        }
        for value, label in LIST_HIDE_OPTIONS
    ]
    drop_states = "watched hidden" if current == "watched_hidden" else ""
    return {"current": current, "options": options, "drop_states": drop_states}


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


def message_context(request: Request) -> dict:
    """The toast of a page reached after a form: `?message=...&level=error`."""
    return {
        "message": request.query_params.get("message"),
        "message_level": request.query_params.get("level", "success"),
    }
