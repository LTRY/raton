"""The time zone of the people who use Raton: where a day starts and ends for them.

The back's container runs in UTC, so the machine's own time zone would cut "today" at UTC
midnight. Everything that reads a clock the way a person does (screen time, Historique, Raton's
visits, the couvre-feu, the daily jobs) goes through here instead.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE_NAME = "Europe/Paris"
LOCAL_TIMEZONE = ZoneInfo(LOCAL_TIMEZONE_NAME)


def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def local_datetime(value: datetime, timezone=LOCAL_TIMEZONE) -> datetime:
    """`value` in `timezone`; a naive one is UTC (what sqlite gives back for a stored date)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)
