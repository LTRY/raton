"""The couvre-feu: a user's nightly range of hours in which the API refuses them everything but
the home page with its chat, the Historique and the writing of a fiche's commentaire
(docs/spec/02-fonctionnalites.md).

The scheduled jobs run in-process and never go through `/api`, so they are not affected.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.user import UserSetting

CURFEW_ENABLED_KEY = "curfew_enabled"
CURFEW_START_KEY = "curfew_start"
CURFEW_END_KEY = "curfew_end"
# ISO datetime with offset: the couvre-feu stays off until then ("pas ce soir").
CURFEW_SKIP_UNTIL_KEY = "curfew_skip_until"
DEFAULT_CURFEW_START = "22:00"
DEFAULT_CURFEW_END = "10:00"
# The person's clock, the scheduler's too: the hours are typed in this time zone.
CURFEW_TIMEZONE = ZoneInfo("Europe/Paris")

# (method, route path) still answered during the couvre-feu: the state itself so a client can say
# why; the home page (Raton, the library chat and its discussions, the user menu); the Historique
# and the commentaire it writes, and the settings, so the user can switch their couvre-feu off.
OPEN_ROUTES = frozenset(
    {
        ("GET", "/api/curfew"),
        ("POST", "/api/curfew/skip"),
        ("DELETE", "/api/curfew/skip"),
        ("GET", "/api/settings"),
        ("PUT", "/api/settings"),
        ("GET", "/api/users"),
        ("POST", "/api/raton/visit"),
        ("GET", "/api/chat"),
        ("POST", "/api/chat"),
        ("GET", "/api/chat/conversations/{conversation_id}"),
        ("DELETE", "/api/chat/conversations/{conversation_id}"),
        ("GET", "/api/llm-jobs/{job_id}"),
        ("GET", "/api/historique"),
        ("GET", "/api/categories"),
        ("PUT", "/api/videos/{video_id}/comment"),
    }
)


class CurfewClosedError(ValueError):
    """An action refused because the couvre-feu is on; the message is shown to the person."""


class CurfewNotSkippableError(ValueError):
    """A couvre-feu that is off or has an empty range has nothing to skip; the message is shown."""


@dataclass(frozen=True)
class Curfew:
    enabled: bool
    start: str
    end: str
    # Enabled, the current time is in the range and it was not skipped for tonight.
    active: bool
    # When the current couvre-feu ends, None when it is not active.
    ends_at: datetime | None
    # When the skip of the current or next couvre-feu ends, None when none is in force.
    skipped_until: datetime | None


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


def read_curfew(db: Session, user_id: int, now: datetime | None = None) -> Curfew:
    """The user's couvre-feu settings and whether it is on at `now` (default: the current time).

    The range runs from `start` included to `end` excluded and may span midnight (22:00 → 10:00);
    `start == end` is an empty range, never active.
    """
    stored = dict(
        db.execute(
            select(UserSetting.key, UserSetting.value).where(
                UserSetting.user_id == user_id,
                UserSetting.key.in_(
                    (CURFEW_ENABLED_KEY, CURFEW_START_KEY, CURFEW_END_KEY, CURFEW_SKIP_UNTIL_KEY)
                ),
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
    skipped_until = _parse_skip_until(stored.get(CURFEW_SKIP_UNTIL_KEY), local)
    ends_at = None
    if enabled and in_range and skipped_until is None:
        ends_on = local.date() if clock < end else local.date() + timedelta(days=1)
        ends_at = datetime.combine(ends_on, end, tzinfo=CURFEW_TIMEZONE)
    return Curfew(
        enabled=enabled,
        start=start.strftime("%H:%M"),
        end=end.strftime("%H:%M"),
        active=ends_at is not None,
        ends_at=ends_at,
        skipped_until=skipped_until,
    )


def _parse_skip_until(value: str | None, now: datetime) -> datetime | None:
    """The stored skip end while it is still in the future, else None."""
    if not value:
        return None
    try:
        until = datetime.fromisoformat(value)
    except ValueError:
        return None
    return until if until > now else None


def _skip_end(start: time, end: time, now: datetime) -> datetime:
    """The end of the couvre-feu in progress, or of the next one when none is in progress."""
    clock = now.time().replace(tzinfo=None)
    in_range = start <= clock < end if start < end else (clock >= start or clock < end)
    if in_range:
        start_day = now.date() - timedelta(days=1) if start > end and clock < end else now.date()
    else:
        start_day = now.date() if clock < start else now.date() + timedelta(days=1)
    end_day = start_day if start < end else start_day + timedelta(days=1)
    return datetime.combine(end_day, end, tzinfo=CURFEW_TIMEZONE)


def skip_curfew_tonight(db: Session, user_id: int, now: datetime | None = None) -> Curfew:
    """Switch the user's couvre-feu off until the end of the current one, or of the next one when
    none is in progress ("pas ce soir"); the settings stay as they are. Commits.

    Raises CurfewNotSkippableError when the couvre-feu is off or its range is empty.
    """
    local = (now or datetime.now(CURFEW_TIMEZONE)).astimezone(CURFEW_TIMEZONE)
    curfew = read_curfew(db, user_id, local)
    start, end = _parse(curfew.start, DEFAULT_CURFEW_START), _parse(curfew.end, DEFAULT_CURFEW_END)
    if not curfew.enabled or start == end:
        raise CurfewNotSkippableError("Le couvre-feu n'est pas activé : il n'y a rien à reporter.")
    _store_skip_until(db, user_id, _skip_end(start, end, local).isoformat())
    return read_curfew(db, user_id, local)


def resume_curfew(db: Session, user_id: int) -> None:
    """Cancel a skip: the couvre-feu applies again. Commits."""
    _store_skip_until(db, user_id, "")


def _store_skip_until(db: Session, user_id: int, value: str) -> None:
    setting = db.get(UserSetting, (user_id, CURFEW_SKIP_UNTIL_KEY))
    if setting is None:
        db.add(UserSetting(user_id=user_id, key=CURFEW_SKIP_UNTIL_KEY, value=value))
    else:
        setting.value = value
    db.commit()


def ensure_open(
    db: Session, user_id: int, method: str, route_path: str, now: datetime | None = None
) -> None:
    """Raise CurfewClosedError when the user's couvre-feu is on and the route is not one it leaves
    open."""
    if (method, route_path) in OPEN_ROUTES:
        return
    curfew = read_curfew(db, user_id, now)
    if curfew.active:
        raise CurfewClosedError(
            f"Couvre-feu jusqu'à {curfew.end} : seuls l'accueil et l'historique restent ouverts, "
            "pour discuter avec Raton et écrire les commentaires."
        )
