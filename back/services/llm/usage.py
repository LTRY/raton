"""Real per-job LLM cost, computed from provider-reported token counts.

Post-run accounting: exact usage is stored on each LlmJob
(back/services/jobs/llm_jobs.py:run_llm_job) and summed up for `GET /api/llm/usage`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from back.models.llm_job import LlmJob


@dataclass(frozen=True)
class ModelPricing:
    """Sticker price of one model, USD per 1M tokens, plus the facts that depend on the model.

    `long_prompt` replaces `input`/`output`/cache prices for a request whose
    whole prompt (uncached + cache reads + cache writes) is over
    `long_prompt_threshold` tokens. Only Haiku 5.5 is priced this way.
    """

    input: float
    output: float
    cache_write: float  # 5-minute TTL write
    cache_read: float
    max_output_tokens: int
    # Same text is ~30% more tokens on the tokenizer introduced with Claude 4.7.
    chars_per_token: float = 4.0
    long_prompt: ModelPricing | None = None
    long_prompt_threshold: int = 100_000


_NEW_TOKENIZER_CHARS_PER_TOKEN = 3.1

# https://platform.claude.com/docs/en/about-claude/pricing — checked 2026-10-07.
ANTHROPIC_MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-haiku-4-5": ModelPricing(1.00, 5.00, 1.25, 0.10, max_output_tokens=64_000),
    "claude-haiku-5-5": ModelPricing(
        0.10,
        0.50,
        0.125,
        0.01,
        max_output_tokens=128_000,
        chars_per_token=_NEW_TOKENIZER_CHARS_PER_TOKEN,
        long_prompt=ModelPricing(0.50, 2.50, 0.625, 0.05, max_output_tokens=128_000),
    ),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00, 3.75, 0.30, max_output_tokens=128_000),
    "claude-sonnet-5": ModelPricing(
        2.00, 10.00, 2.50, 0.20, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-sonnet-5-5": ModelPricing(
        2.00, 10.00, 2.50, 0.10, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-opus-4-6": ModelPricing(5.00, 25.00, 6.25, 0.50, max_output_tokens=128_000),
    "claude-opus-4-7": ModelPricing(
        5.00, 25.00, 6.25, 0.50, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-opus-4-8": ModelPricing(
        5.00, 25.00, 6.25, 0.50, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-opus-5": ModelPricing(5.00, 25.00, 6.25, 0.50, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN),
    "claude-opus-5-5": ModelPricing(
        4.00, 20.00, 5.00, 0.20, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-fable-5": ModelPricing(
        10.00, 50.00, 12.50, 1.00, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
    "claude-fable-5-1": ModelPricing(
        10.00, 50.00, 12.50, 0.25, 128_000, _NEW_TOKENIZER_CHARS_PER_TOKEN
    ),
}

# Message Batches bill every token at half the price (input, output and cache alike).
BATCH_DISCOUNT = 0.5

# Output ceiling for a model missing from the table: Haiku 4.5's, the lowest of the lineup.
DEFAULT_MAX_OUTPUT_TOKENS = 64_000


def max_output_tokens(model: str) -> int:
    pricing = ANTHROPIC_MODEL_PRICING.get(model)
    return pricing.max_output_tokens if pricing else DEFAULT_MAX_OUTPUT_TOKENS


def compute_call_cost_usd(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float | None:
    """Cost of ONE API call. `input_tokens` is the uncached part, as `usage.input_tokens` reports it.

    The Haiku 5.5 price tier depends on the prompt of a single request, so
    a tool loop must be costed call by call and summed, never from its summed tokens.
    Thinking tokens are already part of `output_tokens`.
    """
    pricing = ANTHROPIC_MODEL_PRICING.get(model) if model else None
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    if pricing.long_prompt is not None and prompt_tokens > pricing.long_prompt_threshold:
        pricing = pricing.long_prompt
    return (
        input_tokens * pricing.input
        + cache_write_tokens * pricing.cache_write
        + cache_read_tokens * pricing.cache_read
        + output_tokens * pricing.output
    ) / 1_000_000


def compute_job_cost_usd(
    provider: str, model: str | None, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """Cost of a job made of a single, uncached API call.

    Providers report their own cost on `CompletionResult.cost_usd`; this is the fallback for
    a result that carries none. None for a model missing from the pricing table.
    """
    if provider != "anthropic":
        return None
    return compute_call_cost_usd(model, input_tokens, output_tokens)


LLM_JOB_KIND_LABELS: dict[str, str] = {
    "clean_transcript": "Nettoyage de transcript",
    "generate": "Notes et résumé",
    "auto_notes": "Notes et résumé court (lot nocturne)",
    "notes": "Notes structurées",  # historical, from before notes and summary were merged
    "summary": "Résumé",  # historical, from before notes and summary were merged
    "chat": "Discussion (vidéo)",
    "library_chat": "Discussion (bibliothèque)",
    "detect_sponsors": "Détection de segments sponsorisés",  # historical, from before LLM detection was removed
}


def llm_usage_summary(db: Session) -> dict:
    """Cumulative real usage/cost per job kind, measured since this tracking was added.

    Only counts jobs with a recorded cost_usd (API calls on a known model, including a
    failed job whose response was truncated: its tokens were billed anyway). Jobs that
    are still pending, failed before any response, or ran on an unknown model are
    reported separately as "untracked".
    """
    rows = db.execute(
        select(
            LlmJob.kind,
            func.count(LlmJob.id),
            func.coalesce(func.sum(LlmJob.input_tokens), 0),
            func.coalesce(func.sum(LlmJob.output_tokens), 0),
            func.coalesce(func.sum(LlmJob.cost_usd), 0.0),
        )
        .where(LlmJob.cost_usd.is_not(None))
        .group_by(LlmJob.kind)
        .order_by(LlmJob.kind)
    ).all()
    by_kind = [
        {
            "kind": kind,
            "label": LLM_JOB_KIND_LABELS.get(kind, kind),
            "job_count": job_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
        for kind, job_count, input_tokens, output_tokens, cost_usd in rows
    ]
    model_rows = db.execute(
        select(
            LlmJob.model,
            func.count(LlmJob.id),
            func.coalesce(func.sum(LlmJob.input_tokens), 0),
            func.coalesce(func.sum(LlmJob.output_tokens), 0),
            func.coalesce(func.sum(LlmJob.cost_usd), 0.0),
        )
        .where(LlmJob.cost_usd.is_not(None))
        .group_by(LlmJob.model)
        .order_by(func.sum(LlmJob.cost_usd).desc())
    ).all()
    by_model = [
        {
            "model": model,
            "job_count": job_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
        for model, job_count, input_tokens, output_tokens, cost_usd in model_rows
    ]
    untracked_job_count = (
        db.scalar(select(func.count(LlmJob.id)).where(LlmJob.cost_usd.is_(None))) or 0
    )
    return {
        "by_kind": by_kind,
        "by_model": by_model,
        "total_cost_usd": sum(row["cost_usd"] for row in by_kind),
        "total_job_count": sum(row["job_count"] for row in by_kind),
        "untracked_job_count": untracked_job_count,
    }


# Colour-coded groups of the monthly spend chart on /stats; any kind not listed lands in the last one.
SPEND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Notes et résumés", ("generate", "auto_notes", "notes", "summary")),
    ("Nettoyage de transcript", ("clean_transcript",)),
    ("Discussions", ("chat", "library_chat")),
    ("Autres", ()),
)
_SPEND_MONTHS = 12
_FR_MONTHS = (
    "janv",
    "févr",
    "mars",
    "avr",
    "mai",
    "juin",
    "juil",
    "août",
    "sept",
    "oct",
    "nov",
    "déc",
)


def _spend_group_index(kind: str) -> int:
    for index, (_, kinds) in enumerate(SPEND_GROUPS):
        if kind in kinds:
            return index
    return len(SPEND_GROUPS) - 1


def llm_spend_by_month(db: Session, now: datetime | None = None) -> dict:
    """Real cost per month over the last 12 months, split by `SPEND_GROUPS`, for the /stats chart.

    One bounded query on jobs with a recorded cost (same rule as `llm_usage_summary`);
    leading months before the first spend are dropped. `months` is empty when nothing
    was ever spent in the window.
    """
    now = now or datetime.now(UTC)
    index = now.year * 12 + now.month - 1
    keys = [((i // 12), i % 12 + 1) for i in range(index - _SPEND_MONTHS + 1, index + 1)]
    first = datetime(keys[0][0], keys[0][1], 1, tzinfo=UTC)
    spent = {key: [0.0] * len(SPEND_GROUPS) for key in keys}
    for kind, created_at, cost in db.execute(
        select(LlmJob.kind, LlmJob.created_at, LlmJob.cost_usd).where(
            LlmJob.cost_usd.is_not(None), LlmJob.created_at >= first
        )
    ):
        key = (created_at.year, created_at.month)
        if key in spent:
            spent[key][_spend_group_index(kind)] += float(cost)

    months = [
        {
            "short_label": _FR_MONTHS[month - 1],
            "year": year,
            "total": sum(spent[(year, month)]),
            "parts": [
                {"label": SPEND_GROUPS[i][0], "cost": cost}
                for i, cost in enumerate(spent[(year, month)])
            ],
        }
        for year, month in keys
    ]
    while months and months[0]["total"] == 0:
        months.pop(0)
    peak = max((month["total"] for month in months), default=0.0)
    for month in months:
        month["height"] = round(month["total"] / peak * 100, 1) if peak else 0
        for part in month["parts"]:
            part["percent"] = round(part["cost"] / month["total"] * 100, 1) if month["total"] else 0
    total = sum(month["total"] for month in months)
    return {
        "months": months,
        "legend": [label for label, _ in SPEND_GROUPS],
        "total": total,
        "current": months[-1]["total"]
        if months and months[-1]["short_label"] == _FR_MONTHS[now.month - 1]
        else 0.0,
        "average": total / len(months) if months else 0.0,
    }
