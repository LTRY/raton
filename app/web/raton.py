"""Raton's home-page scenarios: the catalogue, the visit flow, and the picker.

The catalogue below is the single list of ideas, active or not. A scenario with
`active=True` has a condition in `CONDITIONS` and can be shown; the others are
parked ideas that keep their trigger, their lines and the drawing still to make
(see docs/spec/18-raton-scenarios.md). A visit follows a fixed flow: the long
absence line (if any), then one time-of-day greeting, then a random draw among
the remaining lines, never repeating one within the visit.
"""

import json
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.common.settings import (
    SCREEN_TIME_KINDS,
    get_screen_time_limits,
    get_setting,
    set_setting,
)
from app.services.videos.filters import followed_video_condition
from app.services.videos.playback import playback_time_stats

RATON_LAST_SEEN_KEY = "raton_last_seen_at"
RATON_SESSION_PREVIOUS_KEY = "raton_session_previous_visit_at"
# JSON list of the lines already shown in the current visit ("<scenario id>:<rank>").
RATON_SHOWN_KEY = "raton_visit_shown"


# A gap this long between two page loads starts a new visit. Without it a
# refresh right after the "long absence" line would already read as "yesterday".
SESSION_GAP = timedelta(minutes=30)
LONG_ABSENCE_DAYS = 2
# "Late" is from LATE_HOUR to NIGHT_END_HOUR: the home page stops offering videos.
LATE_HOUR = 22
NIGHT_END_HOUR = 5
MINUTES_LEFT_WARNING = 15
CLOSING_RATIO = 1.0
NEAR_LIMIT_RATIO = 0.9

ART_DIR = Path(__file__).resolve().parents[1] / "static" / "img" / "raton"

GROUPS = {
    "moment": "Moment de la journée",
    "temps_ecran": "Temps d'écran",
    "bibliotheque": "Bibliothèque",
    "assistant": "Assistant IA",
    "ailleurs": "À trancher",
}


# Position of a scenario in the flow of a visit.
STAGE_ABSENCE = "absence"  # first load of a visit, when the user was away
STAGE_GREETING = "accueil"  # one line of the time-of-day scenarios
STAGE_DRAW = "tirage"  # every later load: random, no repeat within the visit
STAGE_LABELS = {
    STAGE_ABSENCE: "Longue absence (1er chargement)",
    STAGE_GREETING: "Accueil horaire",
    STAGE_DRAW: "Tirage au hasard",
}


@dataclass(frozen=True)
class Scenario:
    id: str
    group: str
    trigger: str
    # Each line is its text, or a (text, drawing) pair when it has its own drawing.
    lines: tuple[str | tuple[str, str], ...]
    cta_label: str = ""
    cta_href: str = ""
    # File under app/static/img/raton/, or None while the drawing is missing.
    art: str | None = None
    art_brief: str = ""
    active: bool = False
    stage: str = ""
    # Shows the day's limit bar under the line. Also wins the draw: while its
    # condition holds, the other lines of the draw stage are left out.
    closing: bool = False


@dataclass(frozen=True)
class RatonContext:
    now: datetime
    # Highest "watched today / daily limit" among the screen-time kinds.
    limit_ratio: float = 0.0
    minutes_left: float | None = None
    played_today_seconds: float = 0.0
    new_count: int = 0
    previous_visit: datetime | None = None

    def _previous_day(self):
        # The stored visit keeps the offset it was recorded with; compare days in `now`'s zone.
        return self.previous_visit.astimezone(self.now.tzinfo).date()

    @property
    def is_late(self) -> bool:
        return self.now.hour >= LATE_HOUR or self.now.hour < NIGHT_END_HOUR

    @property
    def first_visit_today(self) -> bool:
        return self.previous_visit is None or self._previous_day() < self.now.date()

    @property
    def days_away(self) -> int:
        if self.previous_visit is None:
            return 0
        return (self.now.date() - self._previous_day()).days


CATALOGUE: tuple[Scenario, ...] = (
    # --- Stage 1: long absence
    Scenario(
        id="longue_absence",
        group="bibliotheque",
        trigger="Dernière visite il y a 2 jours ou plus",
        lines=("2j sans toi. Le raton a eu le temps de ranger.",),
        art="rangement.webp",
        active=True,
        stage=STAGE_ABSENCE,
    ),
    # --- Stage 2: time-of-day greeting
    Scenario(
        id="minuit_passe",
        group="moment",
        trigger="Entre minuit et 5 h",
        lines=(
            "Tu me réveilles pour regarder quoi encore comme connerie ?",
            (
                "Les vidéos seront encore là demain. Le sommeil, lui, ne se rattrape pas.",
                "hamac_dos.webp",
            ),
        ),
        art="bonnet_nuit.webp",
        art_brief="Raton en bonnet de nuit au lit, un œil ouvert, lampe de chevet allumée (dessin reçu ; la 2e phrase a son hamac)",
        active=True,
        stage=STAGE_GREETING,
    ),
    Scenario(
        id="matin_tot",
        group="moment",
        trigger="Première visite du jour, de 5 h à 9 h",
        lines=(
            "Le raton n'est pas du matin, mais il est là.",
            "Déjà debout ? Le raton cherche encore son café.",
            "Tôt, hein ? Le raton est là, à moitié.",
            "Déjà là ? Même le café n'est pas prêt.",
        ),
        art="cafetiere.webp",
        art_brief="Raton avec sa tasse devant une cafetière qui goutte encore (dessin reçu)",
        active=True,
        stage=STAGE_GREETING,
    ),
    Scenario(
        id="matin",
        group="moment",
        trigger="Première visite du jour, entre 9 h et 12 h",
        lines=("Va bosser, on bingera après.",),
        art="dossiers.webp",
        active=True,
        stage=STAGE_GREETING,
    ),
    # --- Stage 3: random draw
    Scenario(
        id="ecran_ferme",
        group="temps_ecran",
        trigger="100 % de la limite du jour atteints",
        lines=("C'est tout pour aujourd'hui. Je ferme boutique.",),
        cta_label="Voir l'historique",
        cta_href="/dashboard/historique",
        art="rideau.webp",
        active=True,
        stage=STAGE_DRAW,
        closing=True,
    ),
    Scenario(
        id="nouveautes",
        group="bibliotheque",
        trigger="Au moins une fiche nouvelle (`is_new`)",
        lines=(
            "Il y a du nouveau, Chef.",
            ("Tes youtubeurs ont bossé pendant que tu dormais.", "laptop.webp"),
            ("Le facteur est passé. Il a laissé du contenu.", "facteur.webp"),
        ),
        cta_label="Voir les nouveautés",
        cta_href="/dashboard/nouveautes",
        art="journal.webp",
        active=True,
        stage=STAGE_DRAW,
    ),
    # --- Idées non branchées
    Scenario(
        id="tard",
        group="moment",
        trigger="Entre 22 h et minuit",
        lines=(
            "Va te prendre un livre, ce n'est plus l'heure ici.",
            "Le soir, on lit, on s'étire, on dort. Pas on scrolle.",
            "Je note l'heure. Je ne dis rien, mais je note.",
        ),
        art="journal.webp",
        art_brief="Raton avec un carnet",
    ),
    Scenario(
        id="pause_midi",
        group="moment",
        trigger="Entre 12 h et 14 h, après une lecture dans la journée",
        lines=(
            "Pause déjeuner ? Fais digérer d'abord, regarde après.",
            "Pause méritée. Mais sors un peu, prends l'air.",
            "Midi pile. Ton estomac t'appelle, l'écran peut attendre.",
            "Une sieste, ça se prend sans écran, l'ami.",
        ),
        art="journal.webp",
        art_brief="Raton sur une chaise longue",
    ),
    Scenario(
        id="limite_proche",
        group="temps_ecran",
        trigger="90 % de la limite du jour atteints",
        lines=(
            "Molo l'ami. On a bien bingé à ce que je vois.",
            "Doucement l'ami, il te reste trois miettes de temps d'écran.",
            "Ça sent la fin du festin. Fais gaffe à ce que tu lances.",
        ),
        art="journal.webp",
        art_brief="Raton, doigt levé",
    ),
    Scenario(
        id="quart_d_heure",
        group="temps_ecran",
        trigger="Il reste 15 minutes ou moins avant la limite",
        lines=(
            "Quinze minutes, pas plus. Fais-en bon usage.",
            "Dernier quart d'heure. Une vidéo, pas dix.",
            "Le compte à rebours a commencé, Chef. Tic, tac.",
        ),
        art="journal.webp",
        art_brief="Raton qui regarde sa montre",
    ),
    Scenario(
        id="enchainement",
        group="temps_ecran",
        trigger="3 lectures d'affilée sans pause",
        lines=("Une dernière vidéo ? Tu dis ça depuis tout à l'heure.",),
        art_brief="Raton, bras croisés",
    ),
    Scenario(
        id="prise_tiree",
        group="temps_ecran",
        trigger="Clic sur une lecture après la fermeture",
        lines=("J'ai tiré la prise. Je suis désolé. Presque.",),
        art_brief="Raton débranche une prise",
    ),
    Scenario(
        id="telephone",
        group="temps_ecran",
        trigger="Limite dépassée, 2e passage dans la journée",
        lines=("Juste balance ton téléphone.",),
        art_brief="Raton tend la patte vers l'écran",
    ),
    Scenario(
        id="savais_tu",
        group="bibliotheque",
        trigger="Une fiche liée aux notes ou à une vidéo récente",
        lines=("Savais-tu que…",),
        cta_label="Voir la vidéo",
        art="journal.webp",
        art_brief="Raton avec le journal (dessin reçu)",
    ),
    Scenario(
        id="binge",
        group="bibliotheque",
        trigger="Hier : plus de 2 h ou plus de 5 fiches regardées",
        lines=("(commentaire sur le binge, à écrire au cas par cas)",),
        art="cinema.webp",
    ),
    Scenario(
        id="tache_inachevee",
        group="bibliotheque",
        trigger="Une tâche ou une conversation inachevée",
        lines=("Bonjour chef, on n'a pas fini. On y retourne ?",),
        art_brief="Raton qui tape du pied",
    ),
    Scenario(
        id="clavier_ia",
        group="assistant",
        trigger="Tâche IA en cours (nettoyage, résumé, chat)",
        lines=("(Raton tape au clavier, à la place du balancement)",),
        art_brief="Raton au clavier",
    ),
    Scenario(
        id="chiffres",
        group="assistant",
        trigger="Réponse qui contient des chiffres",
        lines=("Les chiffres ne sont pas bons, vérifie par toi-même.",),
        art_brief="Raton, sourcil levé, calculatrice",
    ),
    Scenario(
        id="erreur",
        group="assistant",
        trigger="Erreur de l'IA ou d'un téléchargement",
        lines=("(Raton la tête dans les mains, comme dans Pokémon)",),
        art_brief="Raton, tête dans les mains",
    ),
    Scenario(
        id="a_reparer",
        group="assistant",
        trigger="Page vide ou à réparer",
        lines=("(Raton avec un marteau et un tournevis)",),
        art_brief="Raton, marteau et tournevis",
    ),
    Scenario(
        id="meteo",
        group="ailleurs",
        trigger="Dehors : la météo",
        lines=("Va voir dehors, il connaît la météo, le malin.",),
        art_brief="Raton à la fenêtre (demande une source météo hors du réseau local)",
    ),
)

# Always true and always last in the list, so the list is never empty.
DEFAULT_SCENARIO = Scenario(
    id="defaut",
    group="moment",
    trigger="Toujours vrai, en dernier",
    lines=("Alors, qu'est-ce qu'on s'envoie aujourd'hui ?",),
    art="popcorn.webp",
    active=True,
    stage=STAGE_DRAW,
)

# Parked scenarios (`tard`, `pause_midi`, `limite_proche`, `quart_d_heure`) have no
# condition here; their thresholds stay above for when they come back.
CONDITIONS = {
    "ecran_ferme": lambda ctx: ctx.limit_ratio >= CLOSING_RATIO,
    "longue_absence": lambda ctx: (
        ctx.previous_visit is not None and ctx.days_away >= LONG_ABSENCE_DAYS
    ),
    "nouveautes": lambda ctx: ctx.new_count > 0 and not ctx.is_late,
    "minuit_passe": lambda ctx: ctx.now.hour < NIGHT_END_HOUR,
    "matin_tot": lambda ctx: ctx.first_visit_today and 5 <= ctx.now.hour < 9,
    "matin": lambda ctx: ctx.first_visit_today and 9 <= ctx.now.hour < 12,
}


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


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_shown(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    return [key for key in parsed if isinstance(key, str)] if isinstance(parsed, list) else []


def record_visit(db: Session, now: datetime) -> tuple[datetime | None, list[str]]:
    """Store this page load; return the previous *visit* (not the previous load) and the lines already shown in this visit."""
    last_seen = _parse_datetime(get_setting(db, RATON_LAST_SEEN_KEY, ""))
    new_visit = last_seen is None or now - last_seen >= SESSION_GAP
    if new_visit:
        set_setting(db, RATON_SESSION_PREVIOUS_KEY, last_seen.isoformat() if last_seen else "")
        shown: list[str] = []
        set_setting(db, RATON_SHOWN_KEY, json.dumps(shown))
    else:
        shown = _parse_shown(get_setting(db, RATON_SHOWN_KEY, "[]"))
    previous = _parse_datetime(get_setting(db, RATON_SESSION_PREVIOUS_KEY, ""))
    set_setting(db, RATON_LAST_SEEN_KEY, now.isoformat())
    db.commit()
    return previous, shown


def screen_time_today(db: Session, now: datetime) -> tuple[float, str, float | None, float]:
    """(highest limit ratio, its kind, fewest minutes left over all kinds, total seconds played today)."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    jobs = list(
        db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played")
            .options(selectinload(DownloadJob.video))
            # One day of margin: `playback_time_stats` does the exact local-day cut.
            .where(DownloadJob.created_at >= day_start.replace(tzinfo=None) - timedelta(days=1))
            .order_by(desc(DownloadJob.created_at))
        )
    )
    stats = playback_time_stats(jobs, now)["today"]
    limits = get_screen_time_limits(db)
    best_ratio, best_kind = 0.0, "video"
    minutes_left: float | None = None
    total_seconds = 0.0
    for kind in SCREEN_TIME_KINDS:
        seconds = float(stats[kind]["seconds"])
        total_seconds += seconds
        limit_minutes = limits[kind]["today"]
        ratio = seconds / (limit_minutes * 60)
        if minutes_left is None or ratio > best_ratio:
            best_ratio, best_kind = ratio, kind
        # The closest limit decides the "15 minutes left" warning, not the busiest kind's.
        left = max(limit_minutes - seconds / 60, 0.0)
        minutes_left = left if minutes_left is None else min(minutes_left, left)
    return best_ratio, best_kind, minutes_left, total_seconds


def build_context(db: Session, now: datetime | None = None) -> RatonContext:
    """Facts about the library and the day; no visit bookkeeping, so it is safe to call from a test page."""
    now = now or datetime.now().astimezone()
    ratio, _, minutes_left, played_seconds = screen_time_today(db, now)
    new_count = (
        db.scalar(
            select(func.count(Video.id))
            .join(Channel, Channel.id == Video.channel_id)
            .where(Video.is_new.is_(True))
            .where(followed_video_condition())
        )
        or 0
    )
    return RatonContext(
        now=now,
        limit_ratio=ratio,
        minutes_left=minutes_left,
        played_today_seconds=played_seconds,
        new_count=new_count,
    )


def home_context(
    db: Session, now: datetime | None = None, rng: random.Random | None = None
) -> dict:
    """Template context of the home hero: the line of this page load."""
    ctx = build_context(db, now)
    previous_visit, shown = record_visit(db, ctx.now)
    ctx = replace(ctx, previous_visit=previous_visit)
    scenario, rank, shown = pick_next(ctx, shown, rng)
    set_setting(db, RATON_SHOWN_KEY, json.dumps(shown))
    db.commit()
    return {
        "scenario": render_line(scenario, rank),
    }
