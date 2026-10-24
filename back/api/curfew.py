"""`/api/curfew`: the couvre-feu state, and the guard every `/api` route goes through."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from back.db.session import get_db
from back.schemas.settings import CurfewRead
from back.services.common.curfew import CurfewClosedError, ensure_open, read_curfew

router = APIRouter(prefix="/api", tags=["Réglages"])


def curfew_read(db: Session) -> CurfewRead:
    curfew = read_curfew(db)
    return CurfewRead(
        enabled=curfew.enabled,
        start=curfew.start,
        end=curfew.end,
        active=curfew.active,
        ends_at=curfew.ends_at,
    )


@router.get("/curfew", response_model=CurfewRead)
def get_curfew(db: Session = Depends(get_db)) -> CurfewRead:
    return curfew_read(db)


def refuse_during_curfew(request: Request, db: Session = Depends(get_db)) -> None:
    """Dependency of the whole `/api` router (`back/api/__init__.py`): 423 during the couvre-feu,
    except on the routes it leaves open."""
    # FastAPI puts the matched route in the scope before solving its dependencies: its path is the
    # template (`/api/videos/{video_id}/comment`), not the requested URL.
    route = request.scope.get("route")
    try:
        ensure_open(db, request.method, getattr(route, "path", request.url.path))
    except CurfewClosedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
