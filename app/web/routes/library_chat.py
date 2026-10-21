from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.jobs.llm_jobs import run_llm_job
from app.services.jobs.llm_requests import (
    LlmJobFailedError,
    LlmJobNotFoundError,
    LlmRequestError,
    find_library_chat_job,
    queue_library_question,
    resolve_llm_job,
)
from app.services.library_chat.history import chat_messages, clear_chat, total_video_count
from app.services.rag.retrieval import count_indexed_videos

router = APIRouter()

# The requests the composer's menu offers; picking one pre-fills the question.
LIBRARY_CHAT_SUGGESTIONS = [
    {"label": "Trouver une chaîne", "prompt": "Quelles chaînes parlent de "},
    {"label": "Trouver une vidéo", "prompt": "Trouve les vidéos sur "},
    {"label": "Interroger mes notes", "prompt": "Que disent mes vidéos sur "},
    {"label": "Ajouter une chaîne YouTube", "prompt": "Ajoute la chaîne de "},
]


def library_chat_payload(db: Session, message: str | None = None) -> dict:
    return {
        "status": "ok",
        "message": message,
        "messages": chat_messages(db),
        "indexed_video_count": count_indexed_videos(db),
        "total_video_count": total_video_count(db),
    }


def library_chat_scope_config(library_chat: dict) -> dict:
    indexed = library_chat["indexed_video_count"]
    total = library_chat["total_video_count"]
    coverage_note = None
    if total:
        coverage_note = (
            f"{indexed} vidéo{'s' if indexed > 1 else ''} indexée{'s' if indexed > 1 else ''} sur {total} "
            "pour la recherche dans les notes (une vidéo devient indexée quand ses notes structurées sont générées)."
        )
    return {
        "askUrl": "/chat",
        "clearUrl": "/chat/clear",
        "jobUrlTemplate": "/chat/jobs/{job_id}",
        "placeholder": "Demander…",
        "suggestions": LIBRARY_CHAT_SUGGESTIONS,
        "messages": library_chat["messages"],
        "coverageNote": coverage_note,
    }


@router.post("/chat")
def chat_about_library(
    request: Request,
    background_tasks: BackgroundTasks,
    question: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        job = queue_library_question(db, question)
    except LlmRequestError as exc:
        return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
    background_tasks.add_task(run_llm_job, job.id)
    return JSONResponse({"status": "queued", "job_id": job.id})


@router.post("/chat/clear")
def clear_library_chat(db: Session = Depends(get_db)):
    clear_chat(db)
    return JSONResponse(library_chat_payload(db, "Discussion effacée."))


@router.get("/chat/jobs/{job_id}")
def library_chat_job_status(job_id: int, db: Session = Depends(get_db)):
    try:
        outcome = resolve_llm_job(db, find_library_chat_job(db, job_id))
    except LlmJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LlmJobFailedError as exc:
        return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
    if outcome.pending:
        return JSONResponse({"status": "pending", "tool_calls": outcome.tool_calls})
    return JSONResponse(library_chat_payload(db, "Réponse ajoutée."))
