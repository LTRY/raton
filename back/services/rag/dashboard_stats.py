"""Aggregates of the `/rag` page: LLM job totals, daily history, chunk statistics, failures, coverage.

Assembled by `rag_dashboard_data` (`dashboard.py`); only DB facts, never files.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from back.models.llm_job import LlmJob
from back.models.video import Video
from back.models.video_note_chunk import EMBEDDING_DIMENSIONS, VideoNoteChunk
from back.services.rag.auto_notes import (
    AUTO_NOTES_KIND,
)
from back.services.rag.indexing import SUMMARY_SECTION_NAME

HISTORY_DAYS = 14


TOP_CHANNELS = 10


RECENT_FAILURES = 8


ERROR_PREVIEW_CHARS = 200


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def percent(part: int | float, whole: int | float) -> float:
    return round(part / whole * 100, 1) if whole else 0


def job_totals(db: Session) -> dict:
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


def daily_history(db: Session, now: datetime) -> list[dict]:
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
            "applied_percent": percent(values["applied"], peak),
            "failed_percent": percent(values["failed"], peak),
            "running_percent": percent(values["running"], peak),
        }
        for key, values in days.items()
    ]


def chunk_stats(db: Session) -> dict:
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
        section["percent"] = percent(section["chunks"], peak)
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
        {"chunks": int(n), "videos": int(count), "percent": percent(count, histogram_peak)}
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
        "newest": aware(newest),
        "sections": sections,
        "histogram": histogram,
        "with_summary": int(with_summary),
        # 4 bytes per float32 dimension, the order of magnitude of the pgvector column.
        "vector_bytes": int(total) * EMBEDDING_DIMENSIONS * 4,
    }


def recent_failures(db: Session) -> list[dict]:
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
            "at": aware(created_at),
        }
        for _, video_id, error, created_at, title in rows
    ]


def channel_coverage(channels: dict[str, Counter[str]]) -> list[dict]:
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
        row["indexed_percent"] = percent(row["indexed"], peak)
        row["pending_percent"] = percent(row["pending"], peak)
        row["failed_percent"] = percent(row["failed"], peak)
        row["coverage"] = round(percent(row["indexed"], row["total"]))
    return rows
