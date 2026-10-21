from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.video import Video
from app.services.jobs.llm_jobs import run_llm_job
from app.services.jobs.llm_requests import LlmRequestError, queue_notes_generation
from app.web.shared import redirect

router = APIRouter()


@router.get("/videos/{video_id}/transcript", response_class=HTMLResponse)
def video_transcript_page(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    target = f"/videos/{video_id}#transcript"
    if request.url.query:
        target = f"/videos/{video_id}?{request.url.query}#transcript"
    return redirect(target)


@router.post("/videos/{video_id}/transcript/generate")
def generate_video_transcript_documents(
    video_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """No-JS fallback of `POST /api/videos/{id}/notes/generate`."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    try:
        job = queue_notes_generation(db, video)
    except LlmRequestError as exc:
        query = urlencode({"level": "error", "message": str(exc)})
        return redirect(f"/videos/{video_id}?{query}#transcript")
    background_tasks.add_task(run_llm_job, job.id)
    return redirect(f"/videos/{video_id}?message=Generation+en+cours...#transcript")
