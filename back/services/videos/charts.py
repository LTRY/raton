"""Aggregations behind the `/stats` page and `GET /api/stats/charts`.

Everything is derived from `videos` rows (no new table): the storage curve is
"what is on disk today, by date added", not a historical record of the used
space — purged media no longer count (see docs/spec/06-stockage-fichiers.md).
"""

from datetime import UTC, datetime

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.settings import get_global_quota_bytes

TOP_CHANNELS = 10
MONTHS_WINDOW = 12
NO_CHANNEL_LABEL = "Sans chaîne"
OTHER_CHANNELS_LABEL = "Autres"

_SHORT_MONTHS = (
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
_LONG_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip

_HAS_MEDIA = (Video.video_path.is_not(None)) | (Video.audio_path.is_not(None))
_IS_SHORT = Video.url.contains("/shorts/")


def _count_if(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0).cast(Integer)


def _channel_rows(db: Session) -> list[dict]:
    """One row per channel (plus the channel-less videos), biggest storage first."""
    name = func.coalesce(Channel.name, NO_CHANNEL_LABEL)
    stmt = (
        select(
            Video.channel_id.label("channel_id"),
            name.label("name"),
            func.coalesce(func.sum(Video.file_size_bytes), 0).label("bytes"),
            func.count(Video.id).label("cards"),
            _count_if(_HAS_MEDIA).label("with_media"),
            _count_if(_IS_SHORT).label("shorts"),
            _count_if(Video.transcript_path.is_not(None)).label("transcripts"),
        )
        .select_from(Video)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .group_by(Video.channel_id, name)
    )
    rows = [
        {
            "channel_id": row.channel_id,
            "name": row.name,
            "bytes": int(row.bytes),
            "cards": int(row.cards),
            "with_media": int(row.with_media),
            "shorts": int(row.shorts),
            "transcripts": int(row.transcripts),
        }
        for row in db.execute(stmt)
    ]
    rows.sort(key=lambda row: (-row["bytes"], -row["cards"], row["name"].lower()))
    return rows


def _top_with_others(rows: list[dict], key: str) -> list[dict]:
    """Keep the `TOP_CHANNELS` biggest rows by `key`, folding the rest into one "Autres" row."""
    ranked = sorted(rows, key=lambda row: (-row[key], row["name"].lower()))
    head, tail = ranked[:TOP_CHANNELS], ranked[TOP_CHANNELS:]
    result = [dict(row) for row in head if row[key] > 0]
    if tail and sum(row[key] for row in tail) > 0:
        folded = {"channel_id": None, "name": f"{OTHER_CHANNELS_LABEL} ({len(tail)})"}
        for field in ("bytes", "cards", "with_media", "shorts", "transcripts"):
            folded[field] = sum(row[field] for row in tail)
        result.append(folded)
    return result


def _with_percent(items: list[dict], key: str) -> list[dict]:
    peak = max((item[key] for item in items), default=0)
    for item in items:
        item["percent"] = round(item[key] / peak * 100, 1) if peak else 0
    return items


def _month_start(value: datetime) -> tuple[int, int]:
    return value.year, value.month


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _monthly(db: Session, now: datetime) -> list[dict]:
    """Cards added and cumulative bytes for the last `MONTHS_WINDOW` months (empty months included)."""
    added = {}
    before_window_bytes = 0
    before_window_cards = 0
    current = _month_start(now)
    first = _shift_month(*current, -(MONTHS_WINDOW - 1))
    for downloaded_at, created_at, size in db.execute(
        select(Video.downloaded_at, Video.created_at, Video.file_size_bytes)
    ):
        moment = downloaded_at or created_at
        if moment is None:
            continue
        key = _month_start(moment)
        if key < first:
            before_window_bytes += int(size or 0)
            before_window_cards += 1
            continue
        cards, used = added.get(key, (0, 0))
        added[key] = (cards + 1, used + int(size or 0))

    months = []
    cumulative_bytes = before_window_bytes
    cumulative_cards = before_window_cards
    for offset in range(MONTHS_WINDOW):
        year, month = _shift_month(*first, offset)
        cards, used = added.get((year, month), (0, 0))
        cumulative_bytes += used
        cumulative_cards += cards
        months.append(
            {
                "label": f"{month:02d}/{str(year)[2:]}",
                "short_label": _SHORT_MONTHS[month - 1],
                "month_name": _LONG_MONTHS[month - 1],
                "year": year,
                "cards_added": cards,
                "bytes_added": used,
                "cumulative_cards": cumulative_cards,
                "cumulative_bytes": cumulative_bytes,
            }
        )
    peak_added = max((m["cards_added"] for m in months), default=0)
    peak_bytes = max((m["cumulative_bytes"] for m in months), default=0)
    for month in months:
        month["cards_percent"] = (
            round(month["cards_added"] / peak_added * 100, 1) if peak_added else 0
        )
        month["bytes_percent"] = (
            round(month["cumulative_bytes"] / peak_bytes * 100, 1) if peak_bytes else 0
        )
    return months


def library_chart_data(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = _channel_rows(db)

    totals = db.execute(
        select(
            func.count(Video.id),
            _count_if(_HAS_MEDIA),
            _count_if(Video.video_path.is_not(None) & Video.audio_path.is_(None)),
            _count_if(Video.audio_path.is_not(None) & Video.video_path.is_(None)),
            _count_if(Video.video_path.is_not(None) & Video.audio_path.is_not(None)),
            func.coalesce(func.sum(case((_IS_SHORT, Video.file_size_bytes), else_=0)), 0),
            func.coalesce(func.sum(Video.file_size_bytes), 0),
        )
    ).one()
    cards, with_media, video_only, audio_only, both, shorts_bytes, total_bytes = (
        int(v) for v in totals
    )
    total_bytes = int(total_bytes)
    shorts_bytes = int(shorts_bytes)

    return {
        "total_cards": cards,
        "total_bytes": total_bytes,
        "storage_by_channel": _with_percent(_top_with_others(rows, "bytes"), "bytes"),
        "cards_by_channel": _with_percent(_top_with_others(rows, "cards"), "cards"),
        "storage_by_kind": [
            {"label": "Vidéos", "bytes": total_bytes - shorts_bytes},
            {"label": "Shorts", "bytes": shorts_bytes},
        ],
        "cards_by_format": [
            {"label": "Vidéo seule", "count": video_only},
            {"label": "Audio seul", "count": audio_only},
            {"label": "Vidéo + audio", "count": both},
            {"label": "Sans média", "count": cards - with_media},
        ],
        "monthly": _monthly(db, now),
    }


def purged_media_by_month(db: Session, now: datetime | None = None) -> dict:
    """Videos whose media the automatic cache purge deleted, per month, for the /stats chart.

    Counts the `purged` rows of `download_jobs` (written once per video by
    `purge_watched_media`) over the last `MONTHS_WINDOW` months; the leading months
    before the first purge are dropped and `months` is empty when nothing was purged.
    """
    now = now or datetime.now(UTC)
    keys = [
        _shift_month(now.year, now.month, -offset) for offset in range(MONTHS_WINDOW - 1, -1, -1)
    ]
    first = datetime(keys[0][0], keys[0][1], 1, tzinfo=UTC)
    counts = dict.fromkeys(keys, 0)
    for (created_at,) in db.execute(
        select(DownloadJob.created_at).where(
            DownloadJob.status == "purged", DownloadJob.created_at >= first
        )
    ):
        key = (created_at.year, created_at.month)
        if key in counts:
            counts[key] += 1

    months = [
        {
            "short_label": _SHORT_MONTHS[month - 1],
            "month_name": _LONG_MONTHS[month - 1],
            "year": year,
            "count": counts[(year, month)],
        }
        for year, month in keys
    ]
    while months and months[0]["count"] == 0:
        months.pop(0)
    peak = max((month["count"] for month in months), default=0)
    for month in months:
        month["percent"] = round(month["count"] / peak * 100, 1) if peak else 0
    total = sum(month["count"] for month in months)
    return {
        "months": months,
        "total": total,
        "current": months[-1]["count"] if months and keys[-1][0] == months[-1]["year"] else 0,
        "average": round(total / len(months)) if months else 0,
    }


def library_stats(db: Session) -> dict:
    """`library_chart_data` plus what `/stats` shows around it: each file type's and format's
    share, the purges, and the storage gauge. The page adds its drawing (`front/charts.py`) and the
    LLM spending (`llm_spend_by_month`), which lives with the LLM services."""
    data = library_chart_data(db)
    used_bytes = data["total_bytes"]
    for kind in data["storage_by_kind"]:
        kind["percent"] = round(kind["bytes"] / used_bytes * 100, 1) if used_bytes else 0
    for item in data["cards_by_format"]:
        item["percent"] = (
            round(item["count"] / data["total_cards"] * 100, 1) if data["total_cards"] else 0
        )
    quota_bytes = get_global_quota_bytes(db)
    return {
        **data,
        "purged": purged_media_by_month(db),
        "quota_bytes": quota_bytes,
        "quota_percent": round(min(used_bytes / quota_bytes * 100, 100), 1)
        if quota_bytes > 0
        else 0,
    }
