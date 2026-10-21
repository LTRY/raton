"""An LlmJob from its creation (`enqueue_llm_job`) to its result (`run_llm_job`)."""

import json
import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.common.job_log import log_job
from app.services.jobs.backfills import run_channel_profile_backfill_job
from app.services.library_chat.history import add_chat_exchange
from app.services.library_chat.schema import LIBRARY_CHAT_TOOLS, MAX_TOOL_TURNS
from app.services.library_chat.tools import LibraryChatToolbox
from app.services.llm.prompts import Prompt, split_generation_result
from app.services.llm.provider import CompletionFailed, get_llm_provider
from app.services.llm.usage import compute_job_cost_usd
from app.services.rag.indexing import index_video_notes
from app.services.videos.documents import append_transcript_chat, write_generated_documents

# How often a streaming `generate` job saves its text so far: short enough that
# the page polling it shows the résumé as it is written, long enough not to
# commit on every token.
PARTIAL_RESULT_INTERVAL_SECONDS = 0.4

logger = logging.getLogger(__name__)


@logged_job("llm")
def run_llm_job(job_id: int) -> None:
    """Run a direct-API completion for a queued LlmJob in the background."""
    added_channel_ids: list[int] = []
    db = SessionLocal()
    try:
        job = db.get(LlmJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()
        try:
            provider_instance = get_llm_provider()
            prompt = Prompt.from_json(job.prompt)
            chunks: list[str] = []
            last_saved = time.monotonic()

            def save_partial_result(delta: str) -> None:
                nonlocal last_saved
                chunks.append(delta)
                if time.monotonic() - last_saved >= PARTIAL_RESULT_INTERVAL_SECONDS:
                    job.result = "".join(chunks)
                    db.commit()
                    last_saved = time.monotonic()

            if job.kind == "library_chat":

                def save_tool_calls(steps: list[dict]) -> None:
                    # Committed right away: the polling request reads it from another session.
                    job.tool_calls = json.dumps(steps)
                    db.commit()

                toolbox = LibraryChatToolbox(db, on_progress=save_tool_calls)
                added_channel_ids = toolbox.added_channel_ids
                completion = provider_instance.complete_with_tools(
                    prompt.messages,
                    LIBRARY_CHAT_TOOLS,
                    toolbox.run,
                    MAX_TOOL_TURNS,
                    system=prompt.system,
                )
                completion.text, sources = toolbox.extract_sources(completion.text)
                job.sources = json.dumps(sources)
            elif job.kind == "generate":
                completion = provider_instance.complete(
                    prompt.messages, on_text=save_partial_result, system=prompt.system
                )
            else:
                completion = provider_instance.complete(prompt.messages, system=prompt.system)
            job.result = completion.text
            job.model = completion.model
            job.input_tokens = completion.input_tokens
            job.output_tokens = completion.output_tokens
            job.cost_usd = (
                completion.cost_usd
                if completion.cost_usd is not None
                else compute_job_cost_usd(
                    job.provider,
                    completion.model,
                    completion.input_tokens,
                    completion.output_tokens,
                )
            )
            job.status = "done"
        except Exception as exc:
            if isinstance(exc, CompletionFailed):
                # The API billed the tokens of a truncated/empty response even though the job failed.
                job.model = exc.usage.model
                job.input_tokens = exc.usage.input_tokens
                job.output_tokens = exc.usage.output_tokens
                job.cost_usd = exc.usage.cost_usd
            job.error = str(exc)
            job.status = "failed"
        job.completed_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()
    if added_channel_ids:
        # After the job is committed as done: the chat answer must not wait for the images.
        # Outside the try/finally so a failed job body never starts a long backfill with
        # its exception pending, and a backfill error cannot replace it.
        try:
            run_channel_profile_backfill_job()
        except Exception:
            logger.exception("Récupération des profils de chaînes échouée après le chat")


def run_notes_indexing_job(video_id: int, notes_text: str, summary_short: str | None) -> None:
    """Index the notes a `generate` job has just written, once the poll that applied them returned."""
    db = SessionLocal()
    try:
        index_video_notes(db, video_id, notes_text, summary_short)
    finally:
        db.close()


def enqueue_llm_job(
    db: Session,
    *,
    kind: str,
    provider: str,
    video_id: int | None,
    prompt: str,
    question: str | None = None,
) -> LlmJob:
    job = LlmJob(
        kind=kind,
        provider=provider,
        video_id=video_id,
        prompt=prompt,
        question=question,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# A finished job ("done") is applied on the first poll that sees it: its result is written where
# the fiche or the chat keeps it, then the job becomes "applied" so a replayed poll writes nothing.


def apply_generation_result(db: Session, video: Video, job: LlmJob) -> dict | None:
    """Write a finished "generate" job's documents; returns what was generated, None if nothing new."""
    if job.status != "done":
        return None
    generated = split_generation_result(job.result or "")
    write_generated_documents(video, generated)
    job.status = "applied"
    db.commit()
    return generated


def apply_transcript_chat_result(db: Session, video: Video, job: LlmJob) -> None:
    if job.status != "done":
        return
    append_transcript_chat(video, job.question or "", job.result or "")
    log_job(
        db,
        "prompt",
        f"Prompt envoyé sur {video.title}: {(job.question or '')[:180]}",
        channel_id=video.channel_id,
        video_id=video.id,
    )
    job.status = "applied"
    db.commit()


def apply_library_chat_result(db: Session, job: LlmJob) -> None:
    if job.status != "done":
        return
    sources = json.loads(job.sources) if job.sources else {}
    add_chat_exchange(
        db,
        job.question or "",
        job.result or "",
        sources.get("video_ids", []),
        sources.get("channel_ids", []),
    )
    log_job(db, "prompt", f"Question bibliothèque : {(job.question or '')[:180]}")
    job.status = "applied"
    db.commit()
