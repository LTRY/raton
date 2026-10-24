"""`/api/users`: the users, and `current_user_id`, the dependency that says whom a request is for.

A client names its user with the `X-Raton-User` header (the front's own calls) or the
`raton_user` cookie (the browser's calls, relayed by the front); a client that names none, such
as the MCP server, acts for the oldest user.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.api.lookups import library_user
from back.db.session import get_db
from back.schemas.user import UserRead, UsersRead, UserWrite
from back.services.common.users import (
    LastUserError,
    UserNameError,
    create_user,
    current_user,
    delete_user,
    list_users,
    rename_user,
)

USER_HEADER = "x-raton-user"
USER_COOKIE = "raton_user"

router = APIRouter(prefix="/api", tags=["Utilisateurs"])


def current_user_id(request: Request, db: Session = Depends(get_db)) -> int:
    requested = request.headers.get(USER_HEADER) or request.cookies.get(USER_COOKIE)
    return current_user(db, requested).id


@router.get("/users", response_model=UsersRead)
def users(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)) -> UsersRead:
    return UsersRead(
        users=[UserRead.model_validate(user) for user in list_users(db)],
        current_user_id=user_id,
    )


@router.post(
    "/users", response_model=UserRead, status_code=201, responses=error_responses(400, 422)
)
def add_user(payload: UserWrite, db: Session = Depends(get_db)) -> UserRead:
    try:
        return UserRead.model_validate(create_user(db, payload.name))
    except UserNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/users/{user_id}", response_model=UserRead, responses=error_responses(400, 404, 422))
def update_user(user_id: int, payload: UserWrite, db: Session = Depends(get_db)) -> UserRead:
    user = library_user(db, user_id)
    try:
        return UserRead.model_validate(rename_user(db, user, payload.name))
    except UserNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/users/{user_id}", status_code=204, responses=error_responses(404, 409, 422))
def remove_user(user_id: int, db: Session = Depends(get_db)) -> None:
    user = library_user(db, user_id)
    try:
        delete_user(db, user)
    except LastUserError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
