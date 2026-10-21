"""`/api/scan`: the channel scan of the 3am cron, started by hand, and its live event feed."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.db.session import get_db
from back.schemas.scan import ScanEventsRead, ScanStartedRead, ScanStatusRead
from back.services.ingest import scan_events
from back.services.ingest.scanner import scan_lock
from back.services.jobs.scheduler import (
    ScanAlreadyRunningError,
    get_last_auto_scan_info,
    run_manual_scan_job,
    start_manual_scan,
)

router = APIRouter(prefix="/api", tags=["Scan"])


@router.get("/scan", response_model=ScanStatusRead)
def get_scan(db: Session = Depends(get_db)) -> ScanStatusRead:
    """Whether a scan runs now, and how the last one went."""
    last = get_last_auto_scan_info(db)
    return ScanStatusRead(
        running=scan_lock.locked(),
        last_event_id=scan_events.events_after(0)[1],
        last_at=last["at"],
        last_status=last["status"],
        last_imported=last["imported"],
    )


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
