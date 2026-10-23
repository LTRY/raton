"""Bodies and replies of the `/api` LLM requests: notes, quiz and discussion of a fiche, library
chat."""

from typing import Literal

from pydantic import BaseModel

from back.schemas.video import ChatMessageRead, QuizQuestionRead, VideoDocumentsRead


class QuestionCreate(BaseModel):
    question: str


class LlmJobQueuedRead(BaseModel):
    job_id: int
    status: str
    status_url: str

    @classmethod
    def from_job(cls, job) -> LlmJobQueuedRead:
        return cls(job_id=job.id, status=job.status, status_url=f"/api/llm-jobs/{job.id}")


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


class LibraryChatRead(BaseModel):
    messages: list[LibraryChatMessageRead]
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
    # `quiz` done: the fiche's new quiz.
    quiz: list[QuizQuestionRead] | None = None
    # `chat` done: the fiche's discussion, with the new answer.
    chat_messages: list[ChatMessageRead] | None = None
    # `library_chat` done: the conversation, with the new answer.
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
