import json

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.models.library_chat_message import LibraryChatMessage
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.common.job_log import log_job
from app.services.common.settings import get_llm_provider_name
from app.services.jobs.llm_jobs import enqueue_llm_job, run_llm_job
from app.services.llm.prompts import build_library_chat_prompt
from app.services.rag.library_chat_tools import parse_source_ids
from app.services.rag.retrieval import count_indexed_videos

router = APIRouter()

# The requests the composer's menu offers; picking one pre-fills the question.
LIBRARY_CHAT_SUGGESTIONS = [
    {"label": "Trouver une chaîne", "prompt": "Quelles chaînes parlent de "},
    {"label": "Trouver une vidéo", "prompt": "Trouve les vidéos sur "},
    {"label": "Interroger mes notes", "prompt": "Que disent mes vidéos sur "},
    {"label": "Ajouter une chaîne YouTube", "prompt": "Ajoute la chaîne de "},
]


def _join_source_ids(ids: list[int]) -> str | None:
    return ",".join(str(item_id) for item_id in ids) or None


def library_chat_payload(db: Session, message: str | None = None) -> dict:
    rows = db.query(LibraryChatMessage).order_by(LibraryChatMessage.id).all()
    video_ids = {video_id for row in rows for video_id in parse_source_ids(row.sources)}
    channel_ids = {
        channel_id for row in rows for channel_id in parse_source_ids(row.channel_sources)
    }
    video_titles = (
        dict(db.query(Video.id, Video.title).filter(Video.id.in_(video_ids)).all())
        if video_ids
        else {}
    )
    channel_names = (
        dict(db.query(Channel.id, Channel.name).filter(Channel.id.in_(channel_ids)).all())
        if channel_ids
        else {}
    )
    messages = [
        {
            "role": row.role,
            "content": row.content,
            # Channels and videos deleted since the answer was given are
            # silently dropped rather than shown as broken links.
            "channels": [
                {"channel_id": channel_id, "name": channel_names[channel_id]}
                for channel_id in parse_source_ids(row.channel_sources)
                if channel_id in channel_names
            ],
            "citations": [
                {"video_id": video_id, "title": video_titles[video_id]}
                for video_id in parse_source_ids(row.sources)
                if video_id in video_titles
            ],
        }
        for row in rows
    ]
    return {
        "status": "ok",
        "message": message,
        "messages": messages,
        "indexed_video_count": count_indexed_videos(db),
        "total_video_count": db.query(Video).count(),
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
    question = question.strip()
    if not question:
        return JSONResponse(
            {"status": "failed", "message": "La question est vide."}, status_code=400
        )
    provider = get_llm_provider_name()
    try:
        history = [
            {"role": row.role, "content": row.content}
            for row in db.query(LibraryChatMessage).order_by(LibraryChatMessage.id).all()
        ]
        prompt = build_library_chat_prompt(history, question)
        job = enqueue_llm_job(
            db,
            kind="library_chat",
            provider=provider,
            video_id=None,
            prompt=prompt,
            question=question,
        )
        background_tasks.add_task(run_llm_job, job.id)
        return JSONResponse({"status": "queued", "job_id": job.id})
    except Exception as exc:
        return JSONResponse(
            {"status": "failed", "message": f"Réponse impossible : {exc}"}, status_code=400
        )


@router.post("/chat/clear")
def clear_library_chat(db: Session = Depends(get_db)):
    db.query(LibraryChatMessage).delete()
    db.commit()
    return JSONResponse(library_chat_payload(db, "Discussion effacée."))


@router.get("/chat/jobs/{job_id}")
def library_chat_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(LlmJob, job_id)
    if job is None or job.kind != "library_chat" or job.video_id is not None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")

    if job.status in ("queued", "running"):
        return JSONResponse(
            {
                "status": "pending",
                "tool_calls": json.loads(job.tool_calls) if job.tool_calls else [],
            }
        )

    if job.status == "failed":
        return JSONResponse(
            {"status": "failed", "message": f"Réponse impossible : {job.error}"}, status_code=400
        )

    try:
        if job.status == "done":
            sources = json.loads(job.sources) if job.sources else {}
            db.add(LibraryChatMessage(role="user", content=job.question or ""))
            db.add(
                LibraryChatMessage(
                    role="assistant",
                    content=job.result or "",
                    sources=_join_source_ids(sources.get("video_ids", [])),
                    channel_sources=_join_source_ids(sources.get("channel_ids", [])),
                )
            )
            log_job(db, "prompt", f"Question bibliothèque : {(job.question or '')[:180]}")
            job.status = "applied"
            db.commit()
        return JSONResponse(library_chat_payload(db, "Réponse ajoutée."))
    except Exception as exc:
        return JSONResponse(
            {"status": "failed", "message": f"Application du résultat impossible : {exc}"},
            status_code=400,
        )
