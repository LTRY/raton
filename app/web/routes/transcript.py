from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.common.settings import get_llm_provider_name
from app.services.jobs.llm_jobs import (
    apply_generation_result,
    apply_transcript_chat_result,
    enqueue_llm_job,
    run_llm_job,
    run_notes_indexing_job,
)
from app.services.llm.prompts import (
    build_chat_prompt,
    build_generation_prompt,
    partial_generation_summary,
)
from app.services.videos.documents import (
    clear_transcript_chat,
    get_transcript_paths,
    load_chat,
    read_transcript_documents,
)
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
    provider = get_llm_provider_name()
    try:
        transcript_path, _, _ = get_transcript_paths(video)
        prompt = build_generation_prompt(
            transcript_path.read_text(encoding="utf-8", errors="replace")
        )
        job = enqueue_llm_job(
            db, kind="generate", provider=provider, video_id=video.id, prompt=prompt
        )
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
    except Exception as exc:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse(
                {"status": "failed", "message": f"Génération impossible : {exc}"}, status_code=400
            )
        query = urlencode({"level": "error", "message": f"Génération impossible : {exc}"})
        return redirect(f"/videos/{video_id}?{query}#transcript")


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
    question = question.strip()
    if not question:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse(
                {"status": "failed", "message": "La question est vide."}, status_code=400
            )
        return redirect(f"/videos/{video_id}#transcript")
    provider = get_llm_provider_name()
    try:
        transcript_path, chat_path, _ = get_transcript_paths(video)
        messages = load_chat(chat_path)
        prompt = build_chat_prompt(
            transcript_path.read_text(encoding="utf-8", errors="replace"), messages, question
        )
        job = enqueue_llm_job(
            db, kind="chat", provider=provider, video_id=video.id, prompt=prompt, question=question
        )
        background_tasks.add_task(run_llm_job, job.id)
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"status": "queued", "job_id": job.id})
        return redirect(f"/videos/{video_id}#discussion")
    except Exception as exc:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse(
                {"status": "failed", "message": f"Réponse impossible : {exc}"}, status_code=400
            )
        query = urlencode({"level": "error", "message": f"Réponse impossible : {exc}"})
        return redirect(f"/videos/{video_id}?{query}#discussion")


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
    job = db.get(LlmJob, job_id)
    if job is None or job.video_id != video_id:
        raise HTTPException(status_code=404, detail="Tâche introuvable")

    if job.status in ("queued", "running"):
        payload = {"status": "pending"}
        if job.kind == "generate" and job.result:
            # run_llm_job saves the text streamed so far in `result`.
            payload["partial_short_summary"] = partial_generation_summary(job.result)
        return JSONResponse(payload)

    if job.status == "failed":
        verb = {
            "generate": "Génération",
        }.get(job.kind, "Réponse")
        return JSONResponse(
            {"status": "failed", "message": f"{verb} impossible : {job.error}"}, status_code=400
        )

    # "done" (first poll after completion) or "applied" (already written, replayed idempotently).
    try:
        if job.kind == "generate":
            generated = apply_generation_result(db, video, job)
            if generated is not None:
                background_tasks.add_task(
                    run_notes_indexing_job,
                    video.id,
                    generated["notes_text"],
                    generated["summary_short"],
                )
            return JSONResponse(
                {
                    "status": "generated",
                    "message": "Notes et résumé générés par l'IA.",
                    **documents_payload(video),
                }
            )

        apply_transcript_chat_result(db, video, job)
        return JSONResponse(chat_payload(video, "Réponse ajoutée."))
    except Exception as exc:
        return JSONResponse(
            {"status": "failed", "message": f"Application du résultat impossible : {exc}"},
            status_code=400,
        )
