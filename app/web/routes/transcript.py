import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.db.session import get_db
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.background_jobs import _video_analysis_has_image, enqueue_llm_job, run_llm_job
from app.services.job_log import log_job
from app.services.llm.provider import (
    ANALYSIS_CLICKBAIT_HEADER,
    build_chat_prompt,
    build_generation_prompt,
    load_chat,
    partial_generation_summary,
    save_chat,
    split_generation_result,
)
from app.services.rag.indexing import index_video_notes
from app.services.settings import get_llm_provider_name
from app.web.shared import redirect

router = APIRouter()


def transcript_context(video: Video) -> dict:
    transcript = None
    notes_transcript = None
    summary_transcript = None
    short_summary = None
    suggested_questions: list[str] = []
    chat_messages = []
    if video.transcript_path:
        path = local_media_path(video.transcript_path)
        if path.is_file():
            transcript = path.read_text(encoding="utf-8", errors="replace")
            notes_path = path.with_name("transcript.notes.txt")
            summary_path = path.with_name("transcript.summary.txt")
            summary_short_path = path.with_name("transcript.summary_short.txt")
            questions_path = path.with_name("transcript.questions.txt")
            chat_path = path.with_name("transcript.chat.json")
            if notes_path.is_file():
                notes_transcript = notes_path.read_text(encoding="utf-8", errors="replace")
            if summary_path.is_file():
                summary_transcript = summary_path.read_text(encoding="utf-8", errors="replace")
            if summary_short_path.is_file():
                short_summary = summary_short_path.read_text(encoding="utf-8", errors="replace")
            if questions_path.is_file():
                suggested_questions = [
                    line.strip()
                    for line in questions_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if line.strip()
                ]
            chat_messages = load_chat(chat_path)
    return {
        "transcript": transcript,
        "notes_transcript": notes_transcript,
        "summary_transcript": summary_transcript,
        "short_summary": short_summary,
        "suggested_questions": suggested_questions,
        "display_transcript": transcript,
        "chat_messages": chat_messages,
    }


@router.get("/videos/{video_id}/transcript", response_class=HTMLResponse)
def video_transcript_page(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    target = f"/videos/{video_id}#transcript"
    if request.url.query:
        target = f"/videos/{video_id}?{request.url.query}#transcript"
    return redirect(target)


def get_transcript_paths(video: Video) -> tuple[Path, Path, Path]:
    if not video.transcript_path:
        raise ValueError("Aucun transcript n'est disponible.")
    transcript_path = local_media_path(video.transcript_path)
    if not transcript_path.is_file():
        raise ValueError("Le fichier transcript est introuvable.")
    return (
        transcript_path,
        transcript_path.with_name("transcript.chat.json"),
        transcript_path.with_name("transcript.notes.txt"),
    )


def documents_payload(video: Video) -> dict:
    context = transcript_context(video)
    transcript = context["transcript"] or ""
    notes_transcript = context["notes_transcript"] or ""
    summary_transcript = context["summary_transcript"] or ""
    return {
        "transcript": transcript,
        "transcript_length": len(transcript),
        "notes_transcript": notes_transcript,
        "notes_length": len(notes_transcript),
        "has_notes": bool(context["notes_transcript"]),
        "summary_transcript": summary_transcript,
        "summary_length": len(summary_transcript),
        "has_summary": bool(context["summary_transcript"]),
        "short_summary": context["short_summary"] or "",
        "suggested_questions": context["suggested_questions"],
        "has_questions": bool(context["suggested_questions"]),
    }


def video_analysis_payload(video: Video) -> dict:
    analysis = json.loads(video.ai_analysis_json) if video.ai_analysis_json else {}
    return {
        "has_analysis": bool(analysis),
        "clickbait_score": analysis.get("clickbait_score"),
        "clickbait_rationale": analysis.get("clickbait_rationale"),
        "relevance_percent": analysis.get("relevance_percent"),
        "relevance_rationale": analysis.get("relevance_rationale"),
        "suggested_titles": analysis.get("suggested_titles") or [],
        "suggested_categories": analysis.get("suggested_categories") or [],
        "generated_at": analysis.get("generated_at"),
    }


def chat_payload(video: Video, message: str | None = None) -> dict:
    context = transcript_context(video)
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
    include_image: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Notes + résumé + analyse in one LLM call (see build_generation_prompt)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    provider = get_llm_provider_name()
    try:
        transcript_path, _, _ = get_transcript_paths(video)
        has_image = bool(include_image) and _video_analysis_has_image(video, provider)
        prompt = build_generation_prompt(
            transcript_path.read_text(encoding="utf-8", errors="replace"), video.title, has_image
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
    try:
        _, chat_path, _ = get_transcript_paths(video)
        chat_path.unlink(missing_ok=True)
    except ValueError:
        pass
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
            short, full = partial_generation_summary(job.result)
            payload["partial_short_summary"] = short
            payload["partial_summary"] = full
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
            if job.status == "done":
                has_image = ANALYSIS_CLICKBAIT_HEADER in job.prompt
                generated = split_generation_result(job.result or "", has_image)
                transcript_path, _, notes_path = get_transcript_paths(video)
                notes_path.write_text(generated["notes_text"], encoding="utf-8")
                background_tasks.add_task(
                    index_video_notes, video.id, generated["notes_text"], generated["summary_short"]
                )
                transcript_path.with_name("transcript.summary.txt").write_text(
                    generated["summary_full"], encoding="utf-8"
                )
                transcript_path.with_name("transcript.summary_short.txt").write_text(
                    generated["summary_short"], encoding="utf-8"
                )
                transcript_path.with_name("transcript.questions.txt").write_text(
                    "\n".join(generated["summary_questions"]), encoding="utf-8"
                )
                analysis = generated["analysis"]
                analysis["generated_at"] = datetime.now(UTC).isoformat()
                video.ai_analysis_json = json.dumps(analysis, ensure_ascii=False)
                job.status = "applied"
                db.commit()
            return JSONResponse(
                {
                    "status": "generated",
                    "message": "Notes, résumé et analyse générés par l'IA.",
                    **documents_payload(video),
                    **video_analysis_payload(video),
                }
            )

        if job.status == "done":
            _, chat_path, _ = get_transcript_paths(video)
            messages = load_chat(chat_path)
            messages.extend(
                [
                    {"role": "user", "content": job.question or ""},
                    {"role": "assistant", "content": job.result or ""},
                ]
            )
            save_chat(chat_path, messages)
            log_job(
                db,
                "prompt",
                f"Prompt envoyé sur {video.title}: {(job.question or '')[:180]}",
                channel_id=video.channel_id,
                video_id=video.id,
            )
            job.status = "applied"
            db.commit()
        return JSONResponse(chat_payload(video, "Réponse ajoutée."))
    except Exception as exc:
        return JSONResponse(
            {"status": "failed", "message": f"Application du résultat impossible : {exc}"},
            status_code=400,
        )
