"""Replies of `/api/raton`: the lines of Raton, the raccoon of the home page."""

from pydantic import BaseModel


class RatonLineRead(BaseModel):
    """One line of a scenario, as a client shows it."""

    id: str
    line: str
    # File name of the drawing, in the front's `static/img/raton/`.
    art: str
    cta_label: str
    cta_href: str
    # The screen-time limit of the day is reached: the line closes the visit.
    closing: bool


class RatonScenarioRead(BaseModel):
    id: str
    stage: str
    trigger: str
    art_brief: str
    lines: list[RatonLineRead]
