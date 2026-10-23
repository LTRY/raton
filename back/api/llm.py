"""`/api` LLM requests: notes of a fiche, its discussion, the library chat, and their jobs.

The discussion and the documents of a fiche are also in `GET /api/videos/{id}`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.api.lookups import fiche
from back.db.session import get_db
from back.models.library_chat_conversation import LibraryChatConversation
from back.models.video import Video
from back.schemas.llm import (
    LibraryChatRead,
    LibraryQuestionCreate,
    LlmJobQueuedRead,
    LlmJobStatusRead,
    LlmUsageRead,
    QuestionCreate,
)
from back.schemas.video import VideoDocumentsRead
from back.services.jobs.llm_jobs import run_llm_job, run_notes_indexing_job
from back.services.jobs.llm_requests import (
    LlmJobFailedError,
    LlmJobNotFoundError,
    LlmRequestError,
    find_llm_job,
    queue_library_question,
    queue_notes_generation,
    queue_video_question,
    resolve_llm_job,
)
from back.services.library_chat.history import (
    ConversationNotFoundError,
    chat_messages,
    delete_conversation,
    get_conversation,
    latest_conversation,
    list_conversations,
    total_video_count,
)
from back.services.llm.usage import llm_usage_summary
from back.services.rag.retrieval import count_indexed_videos
from back.services.videos.documents import clear_transcript_chat, read_transcript_documents

router = APIRouter(prefix="/api", tags=["IA"])


def library_chat_read(db: Session, conversation: LibraryChatConversation | None) -> LibraryChatRead:
    return LibraryChatRead(
        conversation_id=conversation.id if conversation else None,
        title=conversation.title if conversation else None,
        messages=chat_messages(db, conversation.id if conversation else None),
        conversations=list_conversations(db),
        indexed_video_count=count_indexed_videos(db),
        total_video_count=total_video_count(db),
    )


@router.post(
    "/videos/{video_id}/notes/generate",
    response_model=LlmJobQueuedRead,
    status_code=202,
    responses=error_responses(400, 404, 422),
)
def generate_notes(
    video_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> LlmJobQueuedRead:
    """Notes + résumé of the fiche from its transcript, in one LLM call; poll `status_url`."""
    video = fiche(db, video_id)
    try:
        job = queue_notes_generation(db, video)
    except LlmRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_llm_job, job.id)
    return LlmJobQueuedRead.from_job(job)


@router.post(
    "/videos/{video_id}/chat",
    response_model=LlmJobQueuedRead,
    status_code=202,
    responses=error_responses(400, 404, 422),
)
def ask_about_video(
    video_id: int,
    payload: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> LlmJobQueuedRead:
    video = fiche(db, video_id)
    try:
        job = queue_video_question(db, video, payload.question)
    except LlmRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_llm_job, job.id)
    return LlmJobQueuedRead.from_job(job)


@router.delete("/videos/{video_id}/chat", status_code=204, responses=error_responses(404, 422))
def clear_video_chat(video_id: int, db: Session = Depends(get_db)) -> None:
    clear_transcript_chat(fiche(db, video_id))


@router.get("/chat", response_model=LibraryChatRead)
def get_library_chat(db: Session = Depends(get_db)) -> LibraryChatRead:
    """The latest discussion of the library chat, and the list of the others."""
    return library_chat_read(db, latest_conversation(db))


@router.post(
    "/chat",
    response_model=LlmJobQueuedRead,
    status_code=202,
    responses=error_responses(400, 404, 422),
)
def ask_library(
    payload: LibraryQuestionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> LlmJobQueuedRead:
    """A question to the library chat, which searches channels, fiches and notes with its tools.
    Without `conversation_id`, the question starts a new discussion."""
    try:
        job = queue_library_question(db, payload.question, payload.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LlmRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_llm_job, job.id)
    return LlmJobQueuedRead.from_job(job)


@router.get(
    "/chat/conversations/{conversation_id}",
    response_model=LibraryChatRead,
    responses=error_responses(404, 422),
)
def get_library_conversation(
    conversation_id: int, db: Session = Depends(get_db)
) -> LibraryChatRead:
    try:
        conversation = get_conversation(db, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return library_chat_read(db, conversation)


@router.delete(
    "/chat/conversations/{conversation_id}",
    status_code=204,
    responses=error_responses(404, 422),
)
def delete_library_conversation(conversation_id: int, db: Session = Depends(get_db)) -> None:
    try:
        delete_conversation(db, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/llm-jobs/{job_id}", response_model=LlmJobStatusRead, responses=error_responses(404, 422)
)
def get_llm_job(
    job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> LlmJobStatusRead:
    """Where an LLM job stands. The first poll after it finished writes its result (notes,
    answer); a failed job answers 200 with `status: failed`."""
    try:
        job = find_llm_job(db, job_id)
    except LlmJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    fields = {"id": job.id, "kind": job.kind, "video_id": job.video_id}
    try:
        outcome = resolve_llm_job(db, job)
    except LlmJobFailedError as exc:
        return LlmJobStatusRead(**fields, status="failed", message=str(exc))
    if outcome.pending:
        return LlmJobStatusRead(
            **fields,
            status="pending",
            partial_short_summary=outcome.partial_short_summary,
            tool_calls=outcome.tool_calls,
        )
    if outcome.notes_to_index is not None:
        background_tasks.add_task(run_notes_indexing_job, *outcome.notes_to_index)
    if job.kind == "library_chat":
        return LlmJobStatusRead(
            **fields,
            status="done",
            library_chat=library_chat_read(
                db, db.get(LibraryChatConversation, job.conversation_id)
            ),
        )
    documents = read_transcript_documents(db.get(Video, job.video_id))
    if job.kind == "generate":
        return LlmJobStatusRead(
            **fields, status="done", documents=VideoDocumentsRead.from_documents(documents)
        )
    return LlmJobStatusRead(**fields, status="done", chat_messages=documents["chat_messages"])


@router.get("/llm/usage", response_model=LlmUsageRead)
def get_llm_usage(db: Session = Depends(get_db)) -> dict:
    return llm_usage_summary(db)
