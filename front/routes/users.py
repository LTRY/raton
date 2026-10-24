"""Choosing, adding, renaming and deleting a user: the forms of the user menu (home drawer) and of
`/settings`.

The chosen user is the `raton_user` cookie, which only the front sets: every page and every
`/api` call of this browser then acts for that user (see `front/api.py`).
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse

from front.api import USER_COOKIE, Api, ApiError, get_api
from front.pages import append_query, redirect

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
def rename_user(user_id: int, name: str = Form(""), api: Api = Depends(get_api)):
    try:
        api.put(f"/users/{user_id}", {"name": name})
    except ApiError as exc:
        return redirect(append_query("/settings", {"level": "error", "message": exc.detail}))
    return redirect(append_query("/settings", {"message": "Utilisateur renommé."}))


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
