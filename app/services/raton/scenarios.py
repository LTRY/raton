"""Raton's home-page scenarios: the catalogue of ideas and what a scenario holds.

The catalogue below is the single list of ideas, active or not. A scenario with
`active=True` has a condition in `CONDITIONS` and can be shown; the others are
parked ideas that keep their trigger, their lines and the drawing still to make
(see docs/spec/18-raton-scenarios.md). Which line a page load shows is chosen in
`picker.py`; the visit it belongs to is tracked in `visits.py`.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LONG_ABSENCE_DAYS = 2


# "Late" is from LATE_HOUR to NIGHT_END_HOUR: the home page stops offering videos.
LATE_HOUR = 22


NIGHT_END_HOUR = 5


CLOSING_RATIO = 1.0


ART_DIR = Path(__file__).resolve().parents[2] / "static" / "img" / "raton"


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
