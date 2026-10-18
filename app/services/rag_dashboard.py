"""Everything the `/rag` page shows about the notes indexing, derived from the database.

The page answers "where is each video in the pipeline, and what happens tonight?". Nothing here is
stored: the buckets are recomputed from `videos`, `llm_jobs`, `video_note_chunks` and the
`app_settings` keys of the nightly sweep (app/services/auto_notes.py). The classification reuses
`auto_notes.skip_reason`, so the "next batch" list is the one the sweep would submit.

Only database facts are read, never files: the transcript's size and the notes file are checked by
the sweep itself at submission (see `auto_notes.eligible_videos`), so "waiting" is an upper bound.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.channel import Channel
from app.models.llm_job import LlmJob
from app.models.video import Video
from app.models.video_note_chunk import VideoNoteChunk
from app.services.auto_notes import (
    AUTO_NOTES_KIND,
    BATCH_ID_KEY,
    BATCH_SIZE,
    BATCH_STALE_AFTER,
    BATCH_SUBMITTED_AT_KEY,
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
from app.services.embeddings import EMBEDDING_DIMENSIONS
from app.services.rag_indexing import SUMMARY_SECTION_NAME
from app.services.rag_retrieval import (
    CANDIDATE_CHUNKS,
    MAX_CHUNKS_PER_VIDEO,
    MIN_RELEVANCE_SCORE,
    TOP_K_CHUNKS,
)
from app.services.scheduler import DAILY_AUTO_NOTES_HOUR
from app.services.settings import (
    get_auto_notes_enabled,
    get_auto_notes_excluded_category_labels,
    get_setting,
)

SWEEP_TIMEZONE = "Europe/Paris"
HISTORY_DAYS = 14
TOP_CHANNELS = 10
LISTED_VIDEOS = 15
RECENT_FAILURES = 8
ERROR_PREVIEW_CHARS = 200

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
    ("failed", "Abandonnées", "error", f"{MAX_FAILURES_PER_VIDEO} échecs : on n'insiste plus."),
)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _parse_iso(raw: str) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(raw)) if raw else None
    except ValueError:
        return None


def next_sweep_at(now: datetime) -> datetime:
    """The next 5am of the sweep's timezone (a fixed wall-clock hour, like the cron trigger)."""
    local = now.astimezone(ZoneInfo(SWEEP_TIMEZONE))
    candidate = local.replace(hour=DAILY_AUTO_NOTES_HOUR, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def _percent(part: int | float, whole: int | float) -> float:
    return round(part / whole * 100, 1) if whole else 0


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


def _job_totals(db: Session) -> dict:
    rows = db.execute(
        select(
            LlmJob.status,
            func.count(LlmJob.id),
            func.coalesce(func.sum(LlmJob.cost_usd), 0.0),
            func.coalesce(func.sum(LlmJob.input_tokens), 0),
            func.coalesce(func.sum(LlmJob.output_tokens), 0),
        )
        .where(LlmJob.kind == AUTO_NOTES_KIND)
        .group_by(LlmJob.status)
    ).all()
    by_status = {status: count for status, count, *_ in rows}
    cost = sum(row[2] for row in rows)
    input_tokens = sum(row[3] for row in rows)
    output_tokens = sum(row[4] for row in rows)
    applied = by_status.get("applied", 0)
    return {
        "by_status": by_status,
        "jobs": sum(by_status.values()),
        "applied": applied,
        "failed": by_status.get("failed", 0),
        "cost_usd": float(cost),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "avg_cost_usd": float(cost) / applied if applied else None,
        "avg_input_tokens": int(input_tokens / applied) if applied else None,
        "avg_output_tokens": int(output_tokens / applied) if applied else None,
    }


def _daily_history(db: Session, now: datetime) -> list[dict]:
    """Jobs created per day over the last HISTORY_DAYS days, applied/failed/other, with the cost."""
    today = now.date()
    first = today - timedelta(days=HISTORY_DAYS - 1)
    since = datetime(first.year, first.month, first.day, tzinfo=UTC)
    day = func.date(LlmJob.created_at)
    rows = db.execute(
        select(
            day, LlmJob.status, func.count(LlmJob.id), func.coalesce(func.sum(LlmJob.cost_usd), 0.0)
        )
        .where(LlmJob.kind == AUTO_NOTES_KIND, LlmJob.created_at >= since)
        .group_by(day, LlmJob.status)
    ).all()
    days: dict[date, dict] = {
        first + timedelta(days=offset): {"applied": 0, "failed": 0, "running": 0, "cost": 0.0}
        for offset in range(HISTORY_DAYS)
    }
    for raw_day, status, count, cost in rows:
        key = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
        if key in days and status in days[key]:
            days[key][status] += count
        if key in days:
            days[key]["cost"] += float(cost)
    peak = max((d["applied"] + d["failed"] + d["running"] for d in days.values()), default=0)
    return [
        {
            # Day of the month only: a full date does not fit under a column on a phone.
            "label": str(key.day),
            "date": f"{key.day:02d}/{key.month:02d}",
            **values,
            "total": values["applied"] + values["failed"] + values["running"],
            "applied_percent": _percent(values["applied"], peak),
            "failed_percent": _percent(values["failed"], peak),
            "running_percent": _percent(values["running"], peak),
        }
        for key, values in days.items()
    ]


def _chunk_stats(db: Session) -> dict:
    total, videos, characters, newest = db.execute(
        select(
            func.count(VideoNoteChunk.id),
            func.count(func.distinct(VideoNoteChunk.video_id)),
            func.coalesce(func.sum(func.length(VideoNoteChunk.content)), 0),
            func.max(VideoNoteChunk.created_at),
        )
    ).one()
    sections = [
        {"name": name, "chunks": int(count), "avg_chars": int(avg or 0)}
        for name, count, avg in db.execute(
            select(
                VideoNoteChunk.section,
                func.count(VideoNoteChunk.id),
                func.avg(func.length(VideoNoteChunk.content)),
            )
            .group_by(VideoNoteChunk.section)
            .order_by(func.count(VideoNoteChunk.id).desc(), VideoNoteChunk.section)
        )
    ]
    peak = max((section["chunks"] for section in sections), default=0)
    for section in sections:
        section["percent"] = _percent(section["chunks"], peak)
    per_video = (
        select(VideoNoteChunk.video_id, func.count(VideoNoteChunk.id).label("n"))
        .group_by(VideoNoteChunk.video_id)
        .subquery()
    )
    histogram_rows = db.execute(
        select(per_video.c.n, func.count()).group_by(per_video.c.n).order_by(per_video.c.n)
    ).all()
    histogram_peak = max((count for _, count in histogram_rows), default=0)
    histogram = [
        {"chunks": int(n), "videos": int(count), "percent": _percent(count, histogram_peak)}
        for n, count in histogram_rows
    ]
    with_summary = (
        db.scalar(
            select(func.count(func.distinct(VideoNoteChunk.video_id))).where(
                VideoNoteChunk.section == SUMMARY_SECTION_NAME
            )
        )
        or 0
    )
    return {
        "chunks": int(total),
        "videos": int(videos),
        "characters": int(characters),
        "avg_per_video": round(total / videos, 1) if videos else 0,
        "avg_chars": int(characters / total) if total else 0,
        "newest": _aware(newest),
        "sections": sections,
        "histogram": histogram,
        "with_summary": int(with_summary),
        # 4 bytes per float32 dimension, the order of magnitude of the pgvector column.
        "vector_bytes": int(total) * EMBEDDING_DIMENSIONS * 4,
    }


def _recent_failures(db: Session) -> list[dict]:
    rows = db.execute(
        select(LlmJob.id, LlmJob.video_id, LlmJob.error, LlmJob.created_at, Video.title)
        .outerjoin(Video, Video.id == LlmJob.video_id)
        .where(LlmJob.kind == AUTO_NOTES_KIND, LlmJob.status == "failed")
        .order_by(LlmJob.id.desc())
        .limit(RECENT_FAILURES)
    ).all()
    return [
        {
            "video_id": video_id,
            "title": title or "Vidéo supprimée",
            "error": (error or "Erreur inconnue")[:ERROR_PREVIEW_CHARS],
            "at": _aware(created_at),
        }
        for _, video_id, error, created_at, title in rows
    ]


def _channel_coverage(channels: dict[str, Counter[str]]) -> list[dict]:
    rows = []
    for name, counter in channels.items():
        total = sum(counter.values())
        rows.append(
            {
                "name": name,
                "indexed": counter["indexed"],
                "pending": counter["waiting"] + counter["in_batch"],
                "failed": counter["failed"],
                "total": total,
            }
        )
    rows.sort(key=lambda row: (-row["total"], row["name"].lower()))
    rows = rows[:TOP_CHANNELS]
    peak = max((row["total"] for row in rows), default=0)
    for row in rows:
        row["indexed_percent"] = _percent(row["indexed"], peak)
        row["pending_percent"] = _percent(row["pending"], peak)
        row["failed_percent"] = _percent(row["failed"], peak)
        row["coverage"] = round(_percent(row["indexed"], row["total"]))
    return rows


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

    jobs = _job_totals(db)
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
                "percent": _percent(counts[key], total),
            }
            for key, label, family, help_text in BUCKETS
        ],
        "eligible_total": counts["indexed"]
        + counts["in_batch"]
        + counts["waiting"]
        + counts["failed"],
        "indexed_percent": _percent(
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
            "next_sweep_in": next_sweep_at(now) - now,
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
        "history": _daily_history(db, now),
        "chunks": _chunk_stats(db),
        "channels": _channel_coverage(library["channels"]),
        "failures": _recent_failures(db),
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
