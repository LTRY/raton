"""Which of Raton's lines a page load shows.

A visit follows a fixed flow: the long absence line (if any), then one
time-of-day greeting, then a random draw among the remaining lines, never
repeating one within the visit.
"""

import random

from app.services.raton.scenarios import (
    ART_DIR,
    CATALOGUE,
    CONDITIONS,
    DEFAULT_SCENARIO,
    STAGE_ABSENCE,
    STAGE_DRAW,
    STAGE_GREETING,
    STAGE_LABELS,
    RatonContext,
    Scenario,
)


def active_scenarios() -> list[Scenario]:
    return [scenario for scenario in CATALOGUE if scenario.active]


def line_text(scenario: Scenario, rank: int) -> str:
    line = scenario.lines[rank]
    return line if isinstance(line, str) else line[0]


def line_art(scenario: Scenario, rank: int) -> str:
    line = scenario.lines[rank]
    own = None if isinstance(line, str) else line[1]
    return own or scenario.art or "journal.webp"


def line_key(scenario: Scenario, rank: int) -> str:
    return f"{scenario.id}:{rank}"


def art_files(scenario: Scenario) -> set[str]:
    """Every drawing the scenario uses, its default and the ones of single lines."""
    files = {scenario.art} if scenario.art else set()
    files.update(line[1] for line in scenario.lines if not isinstance(line, str))
    return files


def missing_art() -> list[Scenario]:
    """Scenarios whose drawing is still to make, or whose file is not on disk."""
    return [
        s
        for s in CATALOGUE
        if s.art is None or not all((ART_DIR / f).is_file() for f in art_files(s))
    ]


def _holds(scenario: Scenario, ctx: RatonContext) -> bool:
    return scenario is DEFAULT_SCENARIO or CONDITIONS[scenario.id](ctx)


def stage_lines(ctx: RatonContext, stage: str) -> list[tuple[Scenario, int]]:
    """Every (scenario, rank) of the stage whose scenario holds right now, in catalogue order."""
    lines: list[tuple[Scenario, int]] = []
    for scenario in [*active_scenarios(), DEFAULT_SCENARIO]:
        if scenario.stage == stage and _holds(scenario, ctx):
            lines.extend((scenario, rank) for rank in range(len(scenario.lines)))
    return lines


def draw_pool(ctx: RatonContext) -> list[tuple[Scenario, int]]:
    """The lines of the random draw; a holding `closing` scenario wins over all the others."""
    pool = stage_lines(ctx, STAGE_DRAW)
    closing = [(scenario, rank) for scenario, rank in pool if scenario.closing]
    return closing or pool


def _stage_of_key(key: str) -> str:
    scenario_id = key.rpartition(":")[0]
    for scenario in (*CATALOGUE, DEFAULT_SCENARIO):
        if scenario.id == scenario_id:
            return scenario.stage
    return ""


def pick_next(
    ctx: RatonContext, shown: list[str], rng: random.Random | None = None
) -> tuple[Scenario, int, list[str]]:
    """The line of the next page load of a visit, and the updated list of lines shown.

    Flow: long absence (first load only), then one greeting, then the random draw.
    """
    rng = rng or random.Random()
    # Lines of a scenario that no longer exists (catalogue edited mid-visit) are forgotten.
    shown = [key for key in shown if _stage_of_key(key)]
    stages_shown = {_stage_of_key(key) for key in shown}

    candidates: list[tuple[Scenario, int]] = []
    if not shown:
        candidates = stage_lines(ctx, STAGE_ABSENCE)
    if not candidates and STAGE_GREETING not in stages_shown and STAGE_DRAW not in stages_shown:
        candidates = stage_lines(ctx, STAGE_GREETING)
    if not candidates:
        pool = draw_pool(ctx)
        candidates = [(sc, rank) for sc, rank in pool if line_key(sc, rank) not in shown]
        if not candidates:
            # Everything of the pool was seen: start a new round, but not with the line just shown.
            last = shown[-1] if shown and _stage_of_key(shown[-1]) == STAGE_DRAW else None
            shown = [key for key in shown if _stage_of_key(key) != STAGE_DRAW] + (
                [last] if last else []
            )
            candidates = [
                (sc, rank) for sc, rank in pool if line_key(sc, rank) not in shown
            ] or pool
    scenario, rank = rng.choice(candidates)
    return scenario, rank, [*shown, line_key(scenario, rank)]


def render_line(scenario: Scenario, rank: int) -> dict:
    """What the template shows for one line of a scenario."""
    return {
        "id": scenario.id,
        "line": line_text(scenario, rank),
        "cta_label": scenario.cta_label,
        "cta_href": scenario.cta_href,
        "art": line_art(scenario, rank),
        "closing": scenario.closing,
    }


def all_variations() -> list[dict]:
    """Every line of every active scenario, for the test page; no condition applied."""
    return [
        {
            "id": scenario.id,
            "stage": STAGE_LABELS[scenario.stage],
            "trigger": scenario.trigger,
            "art_brief": scenario.art_brief,
            "lines": [render_line(scenario, rank) for rank in range(len(scenario.lines))],
        }
        for scenario in [*active_scenarios(), DEFAULT_SCENARIO]
    ]
