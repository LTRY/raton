"""Jobs a restart cut short: their background task died with the process, so nothing will ever
move them out of `queued` or `running`."""

import logging
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from back.core.logging import log_event
from back.models.job import DownloadJob
from back.models.llm_job import LlmJob
from back.services.rag.auto_notes import AUTO_NOTES_KIND

logger = logging.getLogger(__name__)

UNFINISHED_STATUSES = ("queued", "running")
INTERRUPTED_MESSAGE = "Interrompu par un redémarrage de Raton."


def fail_interrupted_jobs(db: Session) -> tuple[int, int]:
    """Mark every unfinished download and LLM job as failed; returns how many of each.

    Call it once at startup, from the only back that runs the jobs: an instance sharing the
    database (preview, dev PC) would fail jobs that are running fine elsewhere.
    """
    downloads = db.execute(
        update(DownloadJob)
        .where(DownloadJob.status.in_(UNFINISHED_STATUSES))
        .values(status="failed", message=INTERRUPTED_MESSAGE)
    ).rowcount
    llm = db.execute(
        update(LlmJob)
        .where(
            LlmJob.status.in_(UNFINISHED_STATUSES),
            # A `running` auto-notes job waits for its Message Batch, which outlives the process:
            # the next sweep collects it.
            LlmJob.kind != AUTO_NOTES_KIND,
        )
        .values(status="failed", error=INTERRUPTED_MESSAGE, completed_at=datetime.now(UTC))
    ).rowcount
    db.commit()
    if downloads or llm:
        log_event(
            logger,
            "jobs.interrupted",
            level=logging.WARNING,
            download_jobs=downloads,
            llm_jobs=llm,
        )
    return downloads, llm
