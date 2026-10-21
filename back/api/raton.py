"""`/api/raton`: the line Raton says on the home page, and every line for the test page."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from back.db.session import get_db
from back.schemas.raton import RatonLineRead, RatonScenarioRead
from back.services.raton.picker import all_variations
from back.services.raton.visits import home_context

router = APIRouter(prefix="/api", tags=["Raton"])


@router.post("/raton/visit", response_model=RatonLineRead)
def visit(db: Session = Depends(get_db)) -> RatonLineRead:
    """A visit of the home page: records it and draws the line to show (never twice in a row)."""
    return RatonLineRead(**home_context(db)["scenario"])


@router.get("/raton/variations", response_model=list[RatonScenarioRead])
def variations() -> list[RatonScenarioRead]:
    """Every line of every scenario, with no condition and no visit bookkeeping."""
    return [RatonScenarioRead(**group) for group in all_variations()]
