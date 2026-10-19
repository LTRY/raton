from sqlalchemy.orm import Session

from app.services.common.settings import get_screen_time_limits
from app.services.videos.playback import playback_time_stats, recent_played_jobs
from app.services.videos.stats import library_counts
from app.web.playback import playback_time_dashboard


def library_stats_context(db: Session) -> dict:
    """Library counters, storage gauge and playback-time rings shown on /settings."""
    return {
        **library_counts(db),
        "playback_time_stats": playback_time_dashboard(
            playback_time_stats(recent_played_jobs(db)), get_screen_time_limits(db)
        ),
    }
