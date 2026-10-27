"""Everything the `/rag` page shows about the notes indexing, derived from the database.

The page answers "where is each video in the pipeline, and what happens tonight?". Nothing here is
stored: the buckets are recomputed from `videos`, `llm_jobs`, `video_note_chunks` and the
`app_settings` keys of the nightly sweep (back/services/rag/auto_notes.py). The classification reuses
`auto_notes.skip_reason`, so the "next batch" list is the one the sweep would submit.

Only database facts are read, never files: the transcript's size and the notes file are checked by
the sweep itself at submission (see `auto_notes.eligible_videos`), so "waiting" is an upper bound.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.core.config import get_settings
from back.models.channel import Channel
from back.models.llm_job import LlmJob
from back.models.video import Video
from back.models.video_note_chunk import EMBEDDING_DIMENSIONS, VideoNoteChunk
from back.services.common.settings import (
    get_auto_notes_enabled,
    get_auto_notes_excluded_category_labels,
    get_setting,
)
from back.services.rag.auto_notes import (
    AUTO_NOTES_KIND,
    BATCH_ID_KEY,
    BATCH_SIZE,
    BATCH_STALE_AFTER,
    BATCH_SUBMITTED_AT_KEY,
    DAILY_AUTO_NOTES_HOUR,
    LAST_RUN_AT_KEY,
    LAST_RUN_SUMMARY_KEY,
    MAX_FAILURES_PER_VIDEO,
    MIN_TRANSCRIPT_CHARS,
    candidate_order,
    effective_labels,
    failure_counts,
    in_flight_video_ids,
    skip_reason,
)
from back.services.rag.dashboard_stats import (
    aware,
    channel_coverage,
    chunk_stats,
    daily_history,
    job_totals,
    percent,
    recent_failures,
)
from back.services.rag.retrieval import (
    CANDIDATE_CHUNKS,
    MAX_CHUNKS_PER_VIDEO,
    MIN_RELEVANCE_SCORE,
    TOP_K_CHUNKS,
)

SWEEP_TIMEZONE = "Europe/Paris"


LISTED_VIDEOS = 15


# Funnel order: where a video of the library ends up. `family` picks the colour in the template.
BUCKETS = (
    (
        "indexed",
        "Indexées",
        "ok",
        "Au moins un chunk dans la DB : la recherche sémantique les voit.",
    ),
    (
        "in_batch",
        "Dans le lot en cours",
        "info",
        "Envoyées à Anthropic, résultat attendu au prochain passage.",
    ),
    (
        "waiting",
        "En attente",
        "warn",
        "Éligibles : seront prises dans un prochain lot, les plus récentes d'abord.",
    ),
    (
        "no_transcript",
        "Sans transcript",
        "neutral",
        "Rien à résumer : il faut d'abord un transcript.",
    ),
    ("short", "Shorts", "neutral", "Hors périmètre : trop courts pour des notes utiles."),
    (
        "label",
        "Label exclu",
        "neutral",
        "Un label de catégorie exclu dans les réglages (cuisine, musique…).",
    ),
    (
        "channel_off",
        "Chaîne non indexée",
        "neutral",
        "Le réglage « Indexée par le RAG » de la chaîne est désactivé.",
    ),
    ("failed", "Abandonnées", "error", f"{MAX_FAILURES_PER_VIDEO} échecs : on n'insiste plus."),
)


def _parse_iso(raw: str) -> datetime | None:
    try:
        return aware(datetime.fromisoformat(raw)) if raw else None
    except ValueError:
        return None


def next_sweep_at(now: datetime) -> datetime:
    """The next 5am of the sweep's timezone (a fixed wall-clock hour, like the cron trigger)."""
    local = now.astimezone(ZoneInfo(SWEEP_TIMEZONE))
    candidate = local.replace(hour=DAILY_AUTO_NOTES_HOUR, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def _classify_library(db: Session) -> dict:
    """Put every video in one bucket; keeps the ordered ids of the "waiting" ones."""
    excluded = set(get_auto_notes_excluded_category_labels(db))
    in_flight = in_flight_video_ids(db)
    failures = failure_counts(db)
    indexed = set(db.scalars(select(VideoNoteChunk.video_id).distinct()))
    rows = db.execute(
        select(
            Video.id,
            Video.url,
            Video.category_labels,
            Video.transcript_path,
            Video.channel_id,
            Channel.name,
            Channel.category_labels,
            Channel.rag_indexed,
        )
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .order_by(*candidate_order())
    ).all()
    counts: Counter[str] = Counter()
    waiting_ids: list[int] = []
    channels: dict[str, Counter[str]] = {}
    for (
        video_id,
        url,
        own_labels,
        transcript_path,
        _channel_id,
        channel_name,
        channel_labels,
        channel_indexed,
    ) in rows:
        if video_id in indexed:
            bucket = "indexed"
        else:
            bucket = skip_reason(
                video_id,
                url,
                effective_labels(own_labels, channel_labels),
                excluded,
                in_flight,
                failures,
                channel_indexed is not False,
            )
            if bucket is None:
                bucket = "waiting" if transcript_path else "no_transcript"
        counts[bucket] += 1
        if bucket == "waiting":
            waiting_ids.append(video_id)
        # Shorts and excluded labels are noise in a per-channel coverage: only what could be indexed.
        if bucket in ("indexed", "waiting", "in_batch", "failed"):
            channels.setdefault(channel_name or "Sans chaîne", Counter())[bucket] += 1
    return {
        "total": len(rows),
        "counts": counts,
        "waiting_ids": waiting_ids,
        "in_flight_count": len(in_flight),
        "channels": channels,
        "excluded_labels": sorted(excluded),
    }


def _titled(db: Session, ids: list[int]) -> list[dict]:
    """Title and channel of `ids`, in the order given."""
    if not ids:
        return []
    found = {
        row.id: row
        for row in db.execute(
            select(Video.id, Video.title, Channel.name.label("channel"))
            .outerjoin(Channel, Channel.id == Video.channel_id)
            .where(Video.id.in_(ids))
        )
    }
    return [
        {
            "id": video_id,
            "title": found[video_id].title,
            "channel": found[video_id].channel or "Sans chaîne",
        }
        for video_id in ids
        if video_id in found
    ]


def rag_dashboard_data(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    settings = get_settings()
    library = _classify_library(db)
    counts = library["counts"]
    total = library["total"]
    waiting = counts["waiting"]
    in_flight = library["in_flight_count"]

    batch_id = get_setting(db, BATCH_ID_KEY, "")
    submitted_at = _parse_iso(get_setting(db, BATCH_SUBMITTED_AT_KEY, ""))
    enabled = get_auto_notes_enabled(db)
    if not enabled:
        state, state_label = "disabled", "Désactivé"
    elif not settings.anthropic_api_key:
        state, state_label = "no_key", "Clé Anthropic absente"
    elif batch_id or in_flight:
        state, state_label = "in_flight", "Lot en cours chez Anthropic"
    else:
        state, state_label = "idle", "Aucun lot en cours"

    next_ids = library["waiting_ids"][:BATCH_SIZE]
    next_batch_channels: Counter[str] = Counter()
    next_titles = _titled(db, next_ids)
    for item in next_titles:
        next_batch_channels[item["channel"]] += 1

    jobs = job_totals(db)
    average_cost = jobs["avg_cost_usd"]
    stale_at = submitted_at + BATCH_STALE_AFTER if submitted_at else None
    last_run_raw = get_setting(db, LAST_RUN_AT_KEY, "")

    return {
        "now": now,
        "total_videos": total,
        "buckets": [
            {
                "key": key,
                "label": label,
                "family": family,
                "help": help_text,
                "count": counts[key],
                "percent": percent(counts[key], total),
            }
            for key, label, family, help_text in BUCKETS
        ],
        "eligible_total": counts["indexed"]
        + counts["in_batch"]
        + counts["waiting"]
        + counts["failed"],
        "indexed_percent": percent(
            counts["indexed"],
            counts["indexed"] + counts["in_batch"] + counts["waiting"] + counts["failed"],
        ),
        "pipeline": {
            "state": state,
            "state_label": state_label,
            "enabled": enabled,
            "has_anthropic_key": bool(settings.anthropic_api_key),
            "has_voyage_key": bool(settings.voyage_api_key),
            "batch_id": batch_id,
            "batch_videos": in_flight,
            "submitted_at": submitted_at,
            "abandon_at": stale_at,
            "last_run_at": _parse_iso(last_run_raw),
            "last_run_summary": get_setting(db, LAST_RUN_SUMMARY_KEY, ""),
            "next_sweep_at": next_sweep_at(now),
            "next_sweep_in_seconds": int((next_sweep_at(now) - now).total_seconds()),
            "sweep_timezone": SWEEP_TIMEZONE,
            "excluded_labels": library["excluded_labels"],
        },
        "next_batch": {
            "size": len(next_ids),
            "capacity": BATCH_SIZE,
            "videos": next_titles[:LISTED_VIDEOS],
            "hidden": max(0, len(next_ids) - LISTED_VIDEOS),
            "channels": next_batch_channels.most_common(6),
            "queue_after": max(0, waiting - len(next_ids)),
            "nights_left": ceil(waiting / BATCH_SIZE) if waiting else 0,
            "estimated_cost_usd": average_cost * waiting if average_cost is not None else None,
        },
        "in_flight_videos": _titled(
            db,
            list(
                db.scalars(
                    select(LlmJob.video_id)
                    .where(
                        LlmJob.kind == AUTO_NOTES_KIND,
                        LlmJob.status == "running",
                        LlmJob.video_id.is_not(None),
                    )
                    .order_by(LlmJob.id)
                    .limit(LISTED_VIDEOS)
                )
            ),
        ),
        "jobs": jobs,
        "history": daily_history(db, now),
        "chunks": chunk_stats(db),
        "channels": channel_coverage(library["channels"]),
        "failures": recent_failures(db),
        "parameters": {
            "batch_size": BATCH_SIZE,
            "min_transcript_chars": MIN_TRANSCRIPT_CHARS,
            "max_failures": MAX_FAILURES_PER_VIDEO,
            "stale_hours": int(BATCH_STALE_AFTER.total_seconds() // 3600),
            "embedding_model": settings.embedding_model,
            "rerank_model": settings.rerank_model,
            "dimensions": EMBEDDING_DIMENSIONS,
            "candidate_chunks": CANDIDATE_CHUNKS,
            "top_k": TOP_K_CHUNKS,
            "per_video": MAX_CHUNKS_PER_VIDEO,
            "min_score": MIN_RELEVANCE_SCORE,
        },
    }
