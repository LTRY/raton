from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back.db.session import Base


class LlmJob(Base):
    """A queued LLM completion (notes generation, chat), run out of the request path.

    Jobs are run in a FastAPI background task in the web process itself (see
    back/services/jobs/llm_jobs.py:run_llm_job). The caller gets an immediate `queued` response
    and polls `GET /api/llm-jobs/{job_id}` for the result (see
    docs/spec/09-transcript-et-discussion-llm.md).

    `video_id` is null for `kind="library_chat"`: the cross-video chat has no
    single video to scope the job to; `conversation_id` names its discussion
    instead (null once that discussion is deleted, and on every other kind).

    While a `generate` job is `running`, `result` holds the text streamed so
    far (the status route shows the résumé from it as it is written); it is
    only the complete answer once the job is `done`.

    `model`/`input_tokens`/`output_tokens`/`cost_usd` are only populated for
    jobs that completed successfully (`back/services/jobs/llm_jobs.py:run_llm_job`) — real usage
    reported by the provider itself, not a char-count estimate. Failed/incomplete
    jobs leave these null.
    """

    __tablename__ = "llm_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Who asked: a chat answer is written to that user's discussion.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON, library_chat only: see back/services/jobs/llm_jobs.py:run_llm_job.
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON, library_chat only: the tool calls made so far ([{"label", "result"}]),
    # written while the job runs so the status route can show them live. See
    # back/services/library_chat/tools.py:LibraryChatToolbox.
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    video = relationship("Video")
