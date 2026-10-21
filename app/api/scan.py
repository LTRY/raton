"""`/api/scan`: the channel scan of the 3am cron, started by hand, and its live event feed."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.api.errors import error_responses
from app.schemas.scan import ScanEventsRead, ScanStartedRead
from app.services.ingest import scan_events
from app.services.ingest.scanner import scan_lock
from app.services.jobs.scheduler import (
    ScanAlreadyRunningError,
    run_manual_scan_job,
    start_manual_scan,
)

router = APIRouter(prefix="/api", tags=["Scan"])


@router.post(
    "/scan", response_model=ScanStartedRead, status_code=202, responses=error_responses(409)
)
def start_scan(background_tasks: BackgroundTasks) -> ScanStartedRead:
    try:
        after = start_manual_scan()
    except ScanAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(run_manual_scan_job)
    return ScanStartedRead(after=after)


@router.get("/scan/events", response_model=ScanEventsRead, responses=error_responses(422))
def scan_feed(after: int = Query(0, ge=0)) -> ScanEventsRead:
    """What the scan did since event `after`; the feed lives in the web process's memory."""
    events, last_id = scan_events.events_after(after)
    return ScanEventsRead(events=events, last_id=last_id, running=scan_lock.locked())
