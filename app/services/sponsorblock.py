import json

import httpx

SPONSORBLOCK_API_URL = "https://sponsor.ajay.app/api/skipSegments"
SPONSORBLOCK_TIMEOUT_SECONDS = 10.0


def fetch_sponsorblock_segments(yt_video_id: str, categories: list[str]) -> list[dict]:
    """Query the public SponsorBlock API for one video's known segments.

    Returns [] for "no data yet" (SponsorBlock answers 404 for an unknown
    video) as well as for an empty categories list — both are "nothing to
    show", not errors. Any other HTTP/network failure raises, left to the
    caller to catch (mirrors download_subtitles's own try/except at the call
    site, app/services/yt.py:288-291) — a SponsorBlock outage must never
    break a download or a scan.
    """
    if not categories:
        return []
    response = httpx.get(
        SPONSORBLOCK_API_URL,
        params={"videoID": yt_video_id, "categories": json.dumps(categories)},
        timeout=SPONSORBLOCK_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    segments = []
    for item in payload:
        if not isinstance(item, dict) or item.get("category") not in categories:
            continue
        segment = item.get("segment")
        if not isinstance(segment, list) or len(segment) != 2:
            continue
        segments.append(
            {
                "category": item["category"],
                "start_seconds": float(segment[0]),
                "end_seconds": float(segment[1]),
            }
        )
    return segments
