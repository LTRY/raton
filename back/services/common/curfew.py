"""The couvre-feu: a nightly range of hours in which the API refuses everything but the
Historique and the writing of a fiche's commentaire (docs/spec/02-fonctionnalites.md).

The scheduled jobs run in-process and never go through `/api`, so they are not affected.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.setting import AppSetting

CURFEW_ENABLED_KEY = "curfew_enabled"
CURFEW_START_KEY = "curfew_start"
CURFEW_END_KEY = "curfew_end"
DEFAULT_CURFEW_START = "22:00"
DEFAULT_CURFEW_END = "10:00"
# The person's clock, the scheduler's too: the hours are typed in this time zone.
CURFEW_TIMEZONE = ZoneInfo("Europe/Paris")

# (method, route path) still answered during the couvre-feu: what the Historique page needs to
# list the fiches and save their commentaire, and the state itself so a client can say why.
OPEN_ROUTES = frozenset(
    {
        ("GET", "/api/curfew"),
        ("GET", "/api/historique"),
        ("GET", "/api/categories"),
        ("PUT", "/api/videos/{video_id}/comment"),
    }
)


class CurfewClosedError(ValueError):
    """An action refused because the couvre-feu is on; the message is shown to the person."""


@dataclass(frozen=True)
class Curfew:
    enabled: bool
    start: str
    end: str
    # Enabled and the current time is in the range.
    active: bool
    # When the current couvre-feu ends, None when it is not active.
    ends_at: datetime | None


def normalize_curfew_time(value: str) -> str:
    """`H:MM` or `HH:MM` (what an `<input type="time">` sends) as `HH:MM`; raises ValueError."""
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        raise ValueError("doit être une heure au format HH:MM") from None
    return parsed.strftime("%H:%M")


def _parse(value: str, default: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return datetime.strptime(default, "%H:%M").time()


def read_curfew(db: Session, now: datetime | None = None) -> Curfew:
    """The couvre-feu settings and whether it is on at `now` (default: the current time).

    The range runs from `start` included to `end` excluded and may span midnight (22:00 → 10:00);
    `start == end` is an empty range, never active.
    """
    stored = dict(
        db.execute(
            select(AppSetting.key, AppSetting.value).where(
                AppSetting.key.in_((CURFEW_ENABLED_KEY, CURFEW_START_KEY, CURFEW_END_KEY))
            )
        ).all()
    )
    enabled = stored.get(CURFEW_ENABLED_KEY, "false") == "true"
    start = _parse(stored.get(CURFEW_START_KEY, DEFAULT_CURFEW_START), DEFAULT_CURFEW_START)
    end = _parse(stored.get(CURFEW_END_KEY, DEFAULT_CURFEW_END), DEFAULT_CURFEW_END)
    local = (now or datetime.now(CURFEW_TIMEZONE)).astimezone(CURFEW_TIMEZONE)
    clock = local.time().replace(tzinfo=None)
    if start < end:
        in_range = start <= clock < end
    else:
        in_range = start != end and (clock >= start or clock < end)
    ends_at = None
    if enabled and in_range:
        ends_on = local.date() if clock < end else local.date() + timedelta(days=1)
        ends_at = datetime.combine(ends_on, end, tzinfo=CURFEW_TIMEZONE)
    return Curfew(
        enabled=enabled,
        start=start.strftime("%H:%M"),
        end=end.strftime("%H:%M"),
        active=ends_at is not None,
        ends_at=ends_at,
    )


def ensure_open(db: Session, method: str, route_path: str, now: datetime | None = None) -> None:
    """Raise CurfewClosedError when the couvre-feu is on and the route is not one it leaves open.

    An open route costs no query, so the Historique stays as cheap as without the couvre-feu.
    """
    if (method, route_path) in OPEN_ROUTES:
        return
    curfew = read_curfew(db, now)
    if curfew.active:
        raise CurfewClosedError(
            f"Couvre-feu jusqu'à {curfew.end} : seul l'historique reste ouvert, "
            "pour écrire les commentaires."
        )
