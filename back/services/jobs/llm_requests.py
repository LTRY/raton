"""A question or a generation asked to the LLM, from its queueing to its written result.

`queue_*` build the prompt and create the `LlmJob` a route answers with; the route then hands
`run_llm_job` to its background tasks, which also writes the result when the job is done. A client
polls the job; `resolve_llm_job` says where it stands (see `llm_jobs`).
"""

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from back.models.llm_job import LlmJob
from back.models.video import Video
from back.services.common.raton_language import read_raton_language
from back.services.common.settings import get_llm_provider_name
from back.services.jobs.llm_jobs import (
    APPLY_FAILED_PREFIX,
    apply_llm_job_result,
    enqueue_llm_job,
)
from back.services.library_chat.history import (
    chat_history,
    get_conversation,
    start_conversation,
)
from back.services.llm.prompts import (
    build_chat_prompt,
    build_generation_prompt,
    build_library_chat_prompt,
    partial_generation_summary,
)
from back.services.videos.documents import get_transcript_paths, load_chat, transcript_file


class LlmRequestError(ValueError):
    """The request could not be queued; the message is the one shown to the person."""


class LlmJobNotFoundError(ValueError):
    def __init__(self) -> None:
        super().__init__("Tâche introuvable")


class LlmJobFailedError(ValueError):
    """The job failed, or its result could not be written; the message is ready to show."""


@dataclass
class LlmJobOutcome:
    job: LlmJob
    pending: bool
    # A `generate` job still running: the résumé written so far.
    partial_short_summary: str | None = None
    # A `library_chat` job still running: the tools the model has called so far.
    tool_calls: list = field(default_factory=list)
    # A `generate` job whose notes this poll just wrote (its runner did not): (video_id,
    # notes_text, summary_short), for `run_notes_indexing_job` in the background.
    notes_to_index: tuple[int, str, str | None] | None = None


def _question(question: str) -> str:
    question = question.strip()
    if not question:
        raise LlmRequestError("La question est vide.")
    return question


def queue_notes_generation(db: Session, video: Video) -> LlmJob:
    """Notes + résumé of the fiche in one LLM call (`build_generation_prompt`)."""
    try:
        prompt = build_generation_prompt(
            transcript_file(video).read_text(encoding="utf-8", errors="replace")
        )
        return enqueue_llm_job(
            db,
            kind="generate",
            provider=get_llm_provider_name(),
            video_id=video.id,
            prompt=prompt.to_json(),
        )
    except Exception as exc:
        raise LlmRequestError(f"Génération impossible : {exc}") from exc


def queue_video_question(db: Session, user_id: int, video: Video, question: str) -> LlmJob:
    """A question of the user on the fiche's transcript, following their discussion so far."""
    question = _question(question)
    try:
        transcript_path, chat_path, _ = get_transcript_paths(video, user_id)
        prompt = build_chat_prompt(
            transcript_path.read_text(encoding="utf-8", errors="replace"),
            load_chat(chat_path),
            question,
        )
        return enqueue_llm_job(
            db,
            kind="chat",
            provider=get_llm_provider_name(),
            video_id=video.id,
            prompt=prompt.to_json(),
            question=question,
            user_id=user_id,
        )
    except Exception as exc:
        raise LlmRequestError(f"Réponse impossible : {exc}") from exc


def queue_library_question(
    db: Session, user_id: int, question: str, conversation_id: int | None
) -> LlmJob:
    """A question of the user to the library chat, following their discussion `conversation_id`,
    or starting a new one when it is None. Raises `ConversationNotFoundError` for an unknown
    discussion, or another user's."""
    question = _question(question)
    conversation = (
        start_conversation(db, user_id, question)
        if conversation_id is None
        else get_conversation(db, user_id, conversation_id)
    )
    try:
        language = read_raton_language(db, user_id)
        prompt = build_library_chat_prompt(
            chat_history(db, conversation.id), question, language.address, language.nickname
        )
        return enqueue_llm_job(
            db,
            kind="library_chat",
            provider=get_llm_provider_name(),
            video_id=None,
            prompt=prompt.to_json(),
            question=question,
            conversation_id=conversation.id,
            user_id=user_id,
        )
    except Exception as exc:
        raise LlmRequestError(f"Réponse impossible : {exc}") from exc


def find_llm_job(db: Session, job_id: int) -> LlmJob:
    job = db.get(LlmJob, job_id)
    if job is None:
        raise LlmJobNotFoundError()
    return job


def resolve_llm_job(db: Session, job: LlmJob) -> LlmJobOutcome:
    """Where the job stands. `run_llm_job` has normally written a finished job's result already;
    a "done" one found here (a restart cut it short) is written now, once."""
    if job.status == "done":
        notes_to_index = apply_llm_job_result(db, job)
    else:
        notes_to_index = None
    if job.status in ("queued", "running", "applying"):
        outcome = LlmJobOutcome(job=job, pending=True)
        if job.kind == "generate" and job.result:
            # run_llm_job saves the text streamed so far in `result`.
            outcome.partial_short_summary = partial_generation_summary(job.result)
        if job.kind == "library_chat":
            outcome.tool_calls = json.loads(job.tool_calls) if job.tool_calls else []
        return outcome
    if job.status == "failed":
        if job.error and job.error.startswith(APPLY_FAILED_PREFIX):
            raise LlmJobFailedError(job.error)
        verb = "Génération" if job.kind == "generate" else "Réponse"
        raise LlmJobFailedError(f"{verb} impossible : {job.error}")
    return LlmJobOutcome(job=job, pending=False, notes_to_index=notes_to_index)
