"""`/api/curfew`: the couvre-feu state of the request's user, and the guard every `/api` route
goes through."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.api.users import current_user_id
from back.db.session import get_db
from back.schemas.settings import CurfewRead
from back.services.common.curfew import (
    CurfewClosedError,
    CurfewNotSkippableError,
    ensure_open,
    read_curfew,
    resume_curfew,
    skip_curfew_tonight,
)

router = APIRouter(prefix="/api", tags=["Réglages"])


def curfew_read(db: Session, user_id: int) -> CurfewRead:
    curfew = read_curfew(db, user_id)
    return CurfewRead(
        enabled=curfew.enabled,
        start=curfew.start,
        end=curfew.end,
        active=curfew.active,
        ends_at=curfew.ends_at,
        skipped_until=curfew.skipped_until,
    )


@router.get("/curfew", response_model=CurfewRead)
def get_curfew(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> CurfewRead:
    return curfew_read(db, user_id)


@router.post("/curfew/skip", response_model=CurfewRead, responses=error_responses(400))
def skip_curfew(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> CurfewRead:
    """Switch the couvre-feu off for tonight (until the end of the current or next one)."""
    try:
        skip_curfew_tonight(db, user_id)
    except CurfewNotSkippableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return curfew_read(db, user_id)


@router.delete("/curfew/skip", response_model=CurfewRead)
def cancel_curfew_skip(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> CurfewRead:
    """Cancel tonight's skip: the couvre-feu applies again."""
    resume_curfew(db, user_id)
    return curfew_read(db, user_id)


def refuse_during_curfew(
    request: Request, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> None:
    """Dependency of the whole `/api` router (`back/api/__init__.py`): 423 during the user's
    couvre-feu, except on the routes it leaves open."""
    # FastAPI puts the matched route in the scope before solving its dependencies: its path is the
    # template (`/api/videos/{video_id}/comment`), not the requested URL.
    # `current_user_id` is solved once per request: the routes that act for a user share it.
    route_path = getattr(request.scope.get("route"), "path", request.url.path)
    try:
        ensure_open(db, user_id, request.method, route_path)
    except CurfewClosedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
