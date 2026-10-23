"""Bodies and replies of the `/api` LLM requests: notes, discussion of a fiche, library chat."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from back.schemas.video import ChatMessageRead, VideoDocumentsRead


class QuestionCreate(BaseModel):
    question: str


class LibraryQuestionCreate(QuestionCreate):
    # The discussion the question follows; none starts a new one.
    conversation_id: int | None = None


class LlmJobQueuedRead(BaseModel):
    job_id: int
    status: str
    status_url: str
    # `library_chat` only: the discussion of the question, new or not.
    conversation_id: int | None = None

    @classmethod
    def from_job(cls, job) -> LlmJobQueuedRead:
        return cls(
            job_id=job.id,
            status=job.status,
            status_url=f"/api/llm-jobs/{job.id}",
            conversation_id=job.conversation_id,
        )


class LibraryChatChannelRead(BaseModel):
    channel_id: int
    name: str


class LibraryChatCitationRead(BaseModel):
    video_id: int
    title: str


class LibraryChatMessageRead(BaseModel):
    role: str
    content: str
    # The channels and fiches an answer cites; deleted ones are left out.
    channels: list[LibraryChatChannelRead]
    citations: list[LibraryChatCitationRead]


class LibraryChatConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    updated_at: datetime


class LibraryChatRead(BaseModel):
    # The discussion shown; null (and no messages) when there is none yet.
    conversation_id: int | None
    title: str | None
    messages: list[LibraryChatMessageRead]
    # The latest discussions, most recent first, to switch to another one.
    conversations: list[LibraryChatConversationRead]
    # Fiches whose notes the chat can search, out of the library's.
    indexed_video_count: int
    total_video_count: int


class LlmJobStatusRead(BaseModel):
    """`GET /api/llm-jobs/{id}`, polled until `status` is no longer `pending`."""

    id: int
    kind: str
    video_id: int | None
    status: Literal["pending", "done", "failed"]
    # Only for `failed`: why, ready to show.
    message: str | None = None
    # `generate` still running: the résumé written so far.
    partial_short_summary: str | None = None
    # `library_chat` still running: the tools the model has called so far.
    tool_calls: list[dict] = []
    # `generate` done: the fiche's documents, with the new notes and résumé.
    documents: VideoDocumentsRead | None = None
    # `chat` done: the fiche's discussion, with the new answer.
    chat_messages: list[ChatMessageRead] | None = None
    # `library_chat` done: its discussion, with the new answer.
    library_chat: LibraryChatRead | None = None


class LlmUsageRowRead(BaseModel):
    job_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class LlmKindUsageRead(LlmUsageRowRead):
    kind: str
    # French name of the kind of request ("Notes et résumé"...).
    label: str


class LlmModelUsageRead(LlmUsageRowRead):
    model: str | None


class LlmUsageRead(BaseModel):
    """Real cost of the LLM, since its tracking began: jobs with a recorded cost only."""

    by_kind: list[LlmKindUsageRead]
    # Costliest model first.
    by_model: list[LlmModelUsageRead]
    total_cost_usd: float
    total_job_count: int
    # Jobs with no cost measured: pending, failed before any answer, or an unpriced model.
    untracked_job_count: int
