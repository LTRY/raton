from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.video import Video
from app.services.jobs.llm_jobs import run_llm_job, run_notes_indexing_job
from app.services.jobs.llm_requests import (
    EmptyQuestionError,
    LlmJobFailedError,
    LlmJobNotFoundError,
    LlmRequestError,
    find_video_llm_job,
    queue_notes_generation,
    queue_video_question,
    resolve_llm_job,
)
from app.services.videos.documents import clear_transcript_chat, read_transcript_documents
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


def documents_payload(video: Video) -> dict:
    context = read_transcript_documents(video)
    transcript = context["transcript"] or ""
    notes_transcript = context["notes_transcript"] or ""
    return {
        "transcript": transcript,
        "transcript_length": len(transcript),
        "notes_transcript": notes_transcript,
        "notes_length": len(notes_transcript),
        "has_notes": bool(context["notes_transcript"]),
        "short_summary": context["short_summary"] or "",
        "suggested_questions": context["suggested_questions"],
        "has_questions": bool(context["suggested_questions"]),
    }


def chat_payload(video: Video, message: str | None = None) -> dict:
    context = read_transcript_documents(video)
    return {
        "status": "ok",
        "message": message,
        "messages": context["chat_messages"],
    }


@router.post("/videos/{video_id}/transcript/generate")
def generate_video_transcript_documents(
    request: Request,
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Notes + résumé in one LLM call (see build_generation_prompt)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    try:
        job = queue_notes_generation(db, video)
    except LlmRequestError as exc:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        query = urlencode({"level": "error", "message": str(exc)})
        return redirect(f"/videos/{video_id}?{query}#transcript")
    background_tasks.add_task(run_llm_job, job.id)
    if request.headers.get("x-requested-with") == "fetch":
        # Output length isn't correlated to input length, so there's no
        # reliable duration/cost estimate.
        return JSONResponse(
            {
                "status": "queued",
                "job_id": job.id,
                "estimated_seconds": None,
                "estimated_cost_usd": None,
            }
        )
    return redirect(f"/videos/{video_id}?message=Generation+en+cours...#transcript")


@router.post("/videos/{video_id}/transcript/chat")
def chat_about_video_transcript(
    request: Request,
    video_id: int,
    background_tasks: BackgroundTasks,
    question: str = Form(...),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    is_fetch = request.headers.get("x-requested-with") == "fetch"
    try:
        job = queue_video_question(db, video, question)
    except EmptyQuestionError as exc:
        if is_fetch:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        return redirect(f"/videos/{video_id}#transcript")
    except LlmRequestError as exc:
        if is_fetch:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        query = urlencode({"level": "error", "message": str(exc)})
        return redirect(f"/videos/{video_id}?{query}#discussion")
    background_tasks.add_task(run_llm_job, job.id)
    if is_fetch:
        return JSONResponse({"status": "queued", "job_id": job.id})
    return redirect(f"/videos/{video_id}#discussion")


@router.post("/videos/{video_id}/transcript/chat/clear")
def clear_video_transcript_chat(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    clear_transcript_chat(video)
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse(chat_payload(video, "Discussion effacée."))
    return redirect(f"/videos/{video_id}#discussion")


@router.get("/videos/{video_id}/transcript/jobs/{job_id}")
def transcript_job_status(
    video_id: int, job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    try:
        outcome = resolve_llm_job(db, find_video_llm_job(db, video_id, job_id))
    except LlmJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LlmJobFailedError as exc:
        return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)

    if outcome.pending:
        payload = {"status": "pending"}
        if outcome.partial_short_summary is not None:
            payload["partial_short_summary"] = outcome.partial_short_summary
        return JSONResponse(payload)
    if outcome.job.kind == "generate":
        if outcome.notes_to_index is not None:
            background_tasks.add_task(run_notes_indexing_job, *outcome.notes_to_index)
        return JSONResponse(
            {
                "status": "generated",
                "message": "Notes et résumé générés par l'IA.",
                **documents_payload(video),
            }
        )
    return JSONResponse(chat_payload(video, "Réponse ajoutée."))
