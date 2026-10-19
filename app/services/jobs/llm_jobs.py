"""An LlmJob from its creation (`enqueue_llm_job`) to its result (`run_llm_job`)."""

import json
import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.core.logging import logged_job
from app.db.session import SessionLocal
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.services.jobs.backfills import run_channel_profile_backfill_job
from app.services.llm.prompts import ANALYSIS_CLICKBAIT_HEADER, THUMBNAIL_MEDIA_TYPES
from app.services.llm.provider import AnthropicProvider, CompletionFailed, get_llm_provider
from app.services.llm.usage import compute_job_cost_usd
from app.services.rag.library_chat_tools import (
    LIBRARY_CHAT_TOOLS,
    MAX_TOOL_TURNS,
    LibraryChatToolbox,
)

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
                    job.prompt, LIBRARY_CHAT_TOOLS, toolbox.run, MAX_TOOL_TURNS
                )
                completion.text, sources = toolbox.extract_sources(completion.text)
                job.sources = json.dumps(sources)
            elif (
                job.kind == "generate"
                # The clickbait section is only ever requested in the prompt when the
                # user opted into attaching the thumbnail (see the include_image form
                # field on /transcript/generate) — checking for it here, rather than
                # recomputing video_analysis_has_image blindly, is what makes that
                # opt-out actually take effect instead of always attaching the image
                # whenever one happens to be available.
                and ANALYSIS_CLICKBAIT_HEADER in job.prompt
                and isinstance(provider_instance, AnthropicProvider)
                and job.video is not None
                and video_analysis_has_image(job.video, job.provider)
            ):
                image_path = local_media_path(job.video.thumbnail_path).resolve()
                media_type = THUMBNAIL_MEDIA_TYPES.get(image_path.suffix.lower(), "image/jpeg")
                completion = provider_instance.complete_with_image(
                    job.prompt, image_path.read_bytes(), media_type, on_text=save_partial_result
                )
            elif job.kind == "generate":
                completion = provider_instance.complete(job.prompt, on_text=save_partial_result)
            else:
                completion = provider_instance.complete(job.prompt)
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


def video_analysis_has_image(video: Video, provider: str) -> bool:
    if provider != "anthropic" or not video.thumbnail_path or not video.folder_path:
        return False
    folder = local_media_path(video.folder_path).resolve()
    thumbnail = local_media_path(video.thumbnail_path).resolve()
    return thumbnail.is_file() and thumbnail.is_relative_to(folder)


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
