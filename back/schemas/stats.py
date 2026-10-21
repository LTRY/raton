"""Replies of `/api/stats`, `/api/stats/charts` and `/api/rag`: the data of `/stats` and `/rag`.

They follow `library_stats` / `llm_spend_by_month` (videos/charts, llm/usage) and
`rag_dashboard_data` (rag/dashboard). Percentages are 0 to 100; `label`, `family` and `help`
are the pages' French wording, kept so another client shows the same.
"""

from datetime import datetime

from pydantic import BaseModel


class LibraryCountsRead(BaseModel):
    channels: int
    # Channels with a rating above 0.
    rated_channels: int
    videos: int
    # Fiches with a local audio or video file, shorts apart and in all.
    regular_videos: int
    shorts: int
    downloaded_media: int
    transcripts: int
    used_bytes: int
    quota_bytes: int
    # 0 to 100, capped; 0 without a quota.
    storage_percent: float


class AutoNotesRunRead(BaseModel):
    """The last nightly batch of automatic notes."""

    last_run_at: datetime | None
    last_run_summary: str


class ChannelShareRead(BaseModel):
    channel_id: int | None
    name: str
    bytes: int
    cards: int
    with_media: int
    shorts: int
    transcripts: int
    percent: float


class StorageKindRead(BaseModel):
    label: str
    bytes: int
    percent: float


class CardFormatRead(BaseModel):
    label: str
    count: int
    percent: float


class MonthRead(BaseModel):
    label: str
    short_label: str
    month_name: str
    year: int
    cards_added: int
    bytes_added: int
    cumulative_cards: int
    cumulative_bytes: int
    cards_percent: float
    bytes_percent: float


class PurgedMonthRead(BaseModel):
    short_label: str
    month_name: str
    year: int
    count: int
    percent: float


class PurgedRead(BaseModel):
    """Fiches whose media the automatic purge deleted, per month."""

    months: list[PurgedMonthRead]
    total: int
    current: int
    average: float


class SpendPartRead(BaseModel):
    label: str
    cost: float
    percent: float


class SpendMonthRead(BaseModel):
    short_label: str
    year: int
    total: float
    parts: list[SpendPartRead]
    # Bar height relative to the costliest month.
    height: float


class SpendRead(BaseModel):
    """Real LLM cost per month, in USD."""

    months: list[SpendMonthRead]
    legend: list[str]
    total: float
    current: float
    average: float


class StatsChartsRead(BaseModel):
    """`GET /api/stats/charts`: `monthly` keeps the full 12-month window."""

    total_cards: int
    total_bytes: int
    storage_by_channel: list[ChannelShareRead]
    cards_by_channel: list[ChannelShareRead]
    storage_by_kind: list[StorageKindRead]
    cards_by_format: list[CardFormatRead]
    monthly: list[MonthRead]
    purged: PurgedRead
    quota_bytes: int
    quota_percent: float
    spend: SpendRead


class RagBucketRead(BaseModel):
    key: str
    label: str
    # Colour family of the page: ok, info, warn, neutral, error.
    family: str
    help: str
    count: int
    percent: float


class RagPipelineRead(BaseModel):
    state: str
    state_label: str
    enabled: bool
    has_anthropic_key: bool
    has_voyage_key: bool
    batch_id: str
    batch_videos: int
    submitted_at: datetime | None
    abandon_at: datetime | None
    last_run_at: datetime | None
    last_run_summary: str
    next_sweep_at: datetime
    # Seconds until the next nightly batch is submitted.
    next_sweep_in_seconds: int
    sweep_timezone: str
    excluded_labels: list[str]


class RagVideoRead(BaseModel):
    id: int
    title: str
    channel: str


class RagNextBatchRead(BaseModel):
    size: int
    capacity: int
    videos: list[RagVideoRead]
    hidden: int
    # (channel name, fiches of the batch), most represented first.
    channels: list[tuple[str, int]]
    queue_after: int
    nights_left: int
    estimated_cost_usd: float | None


class RagJobsRead(BaseModel):
    by_status: dict[str, int]
    jobs: int
    applied: int
    failed: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    avg_cost_usd: float | None
    avg_input_tokens: float | None
    avg_output_tokens: float | None


class RagDayRead(BaseModel):
    label: str
    date: str
    applied: int
    failed: int
    running: int
    cost: float
    total: int
    applied_percent: float
    failed_percent: float
    running_percent: float


class RagSectionRead(BaseModel):
    name: str
    chunks: int
    avg_chars: int
    percent: float


class RagHistogramBarRead(BaseModel):
    # Fiches holding exactly `chunks` chunks.
    chunks: int
    videos: int
    percent: float


class RagChunksRead(BaseModel):
    chunks: int
    videos: int
    characters: int
    # An int when it is a whole number, as the page prints it.
    avg_per_video: int | float
    avg_chars: int
    newest: datetime | None
    sections: list[RagSectionRead]
    histogram: list[RagHistogramBarRead]
    with_summary: int
    vector_bytes: int


class RagChannelRead(BaseModel):
    name: str
    indexed: int
    pending: int
    failed: int
    total: int
    indexed_percent: float
    pending_percent: float
    failed_percent: float
    coverage: int


class RagFailureRead(BaseModel):
    video_id: int | None
    title: str
    error: str
    at: datetime | None


class RagParametersRead(BaseModel):
    batch_size: int
    min_transcript_chars: int
    max_failures: int
    stale_hours: int
    embedding_model: str
    rerank_model: str
    dimensions: int
    candidate_chunks: int
    top_k: int
    per_video: int
    min_score: float


class RagDashboardRead(BaseModel):
    """`GET /api/rag`: where each fiche stands in the notes indexing, and what happens tonight."""

    now: datetime
    total_videos: int
    buckets: list[RagBucketRead]
    eligible_total: int
    indexed_percent: float
    pipeline: RagPipelineRead
    next_batch: RagNextBatchRead
    in_flight_videos: list[RagVideoRead]
    jobs: RagJobsRead
    history: list[RagDayRead]
    chunks: RagChunksRead
    channels: list[RagChannelRead]
    failures: list[RagFailureRead]
    parameters: RagParametersRead
