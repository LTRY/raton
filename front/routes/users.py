"""The user's own page (`/user`, opened from the home drawer's round button: their name, the
user switch, Raton's language, the couvre-feu), and the user forms of that page and of
`/settings`.

The chosen user is the `raton_user` cookie, which only the front sets: every page and every
`/api` call of this browser then acts for that user (see `front/api.py`).
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from front.api import USER_COOKIE, Api, ApiError, get_api
from front.forms import form_text_value
from front.library_chat import user_menu
from front.pages import append_query, internal_return_path, message_context, redirect
from front.records import record
from front.templating import templates

router = APIRouter()

# Ten years: the choice stays until the person picks another user.
USER_COOKIE_MAX_AGE = 10 * 365 * 24 * 3600


def act_as(response: RedirectResponse, user_id: int) -> RedirectResponse:
    response.set_cookie(
        USER_COOKIE, str(user_id), max_age=USER_COOKIE_MAX_AGE, samesite="lax", httponly=True
    )
    return response


def _users(api: Api) -> dict[int, str]:
    return {user["id"]: user["name"] for user in api.get("/users")["users"]}


@router.get("/user", response_class=HTMLResponse)
def user_page(request: Request, api: Api = Depends(get_api)):
    """Open during the couvre-feu (its API calls are): the name, the user addition and Raton's
    language are then hidden, and the couvre-feu card stays so that it can be switched off."""
    settings = api.get("/settings")
    curfew = record(settings["curfew"])
    return templates.TemplateResponse(
        request,
        "user_settings.html",
        {
            "users": user_menu(api.get("/users")),
            "curfew": curfew,
            "curfew_mode": curfew.active,
            "raton_language": record(settings["raton_language"]),
            **message_context(request),
        },
    )


@router.post("/user")
def user_form(
    raton_address: str | None = Form(None),
    raton_nickname: str | None = Form(None),
    curfew_enabled: str = Form(default=""),
    curfew_start: str = Form("22:00"),
    curfew_end: str = Form("10:00"),
    api: Api = Depends(get_api),
):
    try:
        api.put(
            "/settings",
            {
                # During the couvre-feu the form only holds the couvre-feu card: the language
                # fields are absent and stay as they are.
                "raton_address": raton_address,
                "raton_nickname": None
                if raton_nickname is None
                else form_text_value(raton_nickname),
                # Unchecked checkbox: the browser sends nothing, so an empty value means "off".
                "curfew_enabled": bool(form_text_value(curfew_enabled)),
                "curfew_start": curfew_start,
                "curfew_end": curfew_end,
            },
        )
    except ApiError as exc:
        if exc.status == 423:
            raise
        return redirect(append_query("/user", {"level": "error", "message": exc.detail}))
    return redirect(append_query("/user", {"message": "Paramètres enregistrés."}))


@router.post("/user/curfew/skip")
def skip_curfew(api: Api = Depends(get_api)):
    """Switch the couvre-feu off for tonight."""
    try:
        api.post("/curfew/skip")
    except ApiError as exc:
        return redirect(append_query("/user", {"level": "error", "message": exc.detail}))
    return redirect(append_query("/user", {"message": "Couvre-feu désactivé pour ce soir."}))


@router.post("/user/curfew/resume")
def resume_curfew(api: Api = Depends(get_api)):
    """Cancel tonight's skip."""
    api.delete("/curfew/skip")
    return redirect(append_query("/user", {"message": "Couvre-feu rétabli."}))


@router.post("/users/switch")
def switch_user(user_id: int = Form(...), api: Api = Depends(get_api)):
    """Act as another user; the home page then shows their discussions and Raton's line."""
    name = _users(api).get(user_id)
    if name is None:
        return redirect(
            append_query("/", {"level": "error", "message": "Utilisateur introuvable."})
        )
    return act_as(redirect(append_query("/", {"message": f"Bonjour {name} !"})), user_id)


@router.post("/users")
def add_user(name: str = Form(""), api: Api = Depends(get_api)):
    """Add a user and act as them right away."""
    try:
        user = api.post("/users", {"name": name})
    except ApiError as exc:
        return redirect(append_query("/", {"level": "error", "message": exc.detail}))
    return act_as(redirect(append_query("/", {"message": f"Bonjour {user['name']} !"})), user["id"])


@router.post("/users/{user_id}/rename")
def rename_user(
    user_id: int,
    name: str = Form(""),
    return_to: str = Form("/settings", alias="next"),
    api: Api = Depends(get_api),
):
    back_to = internal_return_path(return_to, "/settings")
    try:
        api.put(f"/users/{user_id}", {"name": name})
    except ApiError as exc:
        if exc.status == 423:
            raise
        return redirect(append_query(back_to, {"level": "error", "message": exc.detail}))
    return redirect(append_query(back_to, {"message": "Utilisateur renommé."}))


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, api: Api = Depends(get_api)):
    """Delete a user and what was theirs; deleting oneself goes back to the default user."""
    try:
        api.delete(f"/users/{user_id}")
    except ApiError as exc:
        return redirect(append_query("/settings", {"level": "error", "message": exc.detail}))
    response = redirect(append_query("/settings", {"message": "Utilisateur supprimé."}))
    if api.user == str(user_id):
        response.delete_cookie(USER_COOKIE)
    return response
