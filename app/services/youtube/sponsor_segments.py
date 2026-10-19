from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.video_sponsor_segment import VideoSponsorSegment
from app.services.common.settings import get_sponsor_segment_categories
from app.services.youtube.sponsorblock import fetch_sponsorblock_segments

MINIMUM_SKIP_SECONDS: float = 1.0


def replace_video_sponsor_segments(
    db: Session, video_id: int, source: str, segments: list[dict]
) -> list[VideoSponsorSegment]:
    """Remplace tous les segments de `source` d'une vidéo par `segments`.

    SponsorBlock (app/services/youtube/sponsorblock.py) est la seule source aujourd'hui,
    mais l'écriture reste limitée aux lignes de sa propre `source` : relancer son
    bouton de récupération ne touche jamais aux lignes écrites par une autre
    source. La colonne `source` est conservée pour cette raison, afin qu'une
    seconde source puisse être ajoutée sans migration.
    """
    db.execute(
        delete(VideoSponsorSegment).where(
            VideoSponsorSegment.video_id == video_id, VideoSponsorSegment.source == source
        )
    )
    rows = [
        VideoSponsorSegment(
            video_id=video_id,
            category=segment["category"],
            start_seconds=segment["start_seconds"],
            end_seconds=segment["end_seconds"],
            source=source,
        )
        for segment in segments
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def normalize_skip_segments(rows: Iterable[VideoSponsorSegment]) -> list[dict[str, float]]:
    """Prépare les segments pour les lecteurs : tri, fusion, filtrage.

    SponsorBlock renvoie régulièrement des segments qui se chevauchent ou se
    touchent (plusieurs contributeurs sur la même vidéo) : sans fusion, deux
    sponsors collés déclencheraient deux fondus consécutifs. Les segments plus
    courts que MINIMUM_SKIP_SECONDS sont écartés — un fondu de 250 ms de part et
    d'autre coûterait plus cher que le segment lui-même.

    Les catégories ne sont pas conservées : le moteur de saut ne compare que des
    bornes. Le filtrage par catégories activées reste à la charge de l'appelant
    (clause `category.in_(...)` de la requête SQL).
    """
    ordered = sorted((float(row.start_seconds), float(row.end_seconds)) for row in rows)
    merged: list[list[float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        {"start": start, "end": end} for start, end in merged if end - start >= MINIMUM_SKIP_SECONDS
    ]


def active_sponsor_segments(db: Session, video_id: int) -> list[VideoSponsorSegment]:
    """The fiche's segments of the categories enabled in the settings, in playback order.

    A list, not the `ScalarResult`: callers read the rows twice (the list shown and the skip payload).
    """
    categories = get_sponsor_segment_categories(db)
    if not categories:
        return []
    return list(
        db.scalars(
            select(VideoSponsorSegment)
            .where(
                VideoSponsorSegment.video_id == video_id,
                VideoSponsorSegment.category.in_(categories),
            )
            .order_by(VideoSponsorSegment.start_seconds)
        )
    )


def fetch_sponsor_segments(db: Session, video) -> list[VideoSponsorSegment]:
    """Ask SponsorBlock for the fiche's segments of the enabled categories and store them.

    Raises on a SponsorBlock or database failure; the caller decides whether that matters.
    """
    categories = get_sponsor_segment_categories(db)
    segments = fetch_sponsorblock_segments(video.yt_video_id, categories)
    return replace_video_sponsor_segments(db, video.id, "sponsorblock", segments)
