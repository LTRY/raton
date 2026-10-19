"""Template context of the page of a fiche: labels and links around `VideoDetail`."""

from app.services.common.durations import format_duration
from app.services.common.settings import (
    SPONSOR_SEGMENT_CATEGORY_LABELS,
    get_llm_provider_display_label,
)
from app.services.videos.detail_view import VideoDetail
from app.web.formatting import format_views
from app.web.shared import category_style_map


def back_label(back_path: str) -> str:
    if back_path.startswith("/playlists/"):
        return "Retour à la playlist"
    if "channel_id=" in back_path:
        return "Retour à la chaîne"
    return "Retour à la bibliothèque"


def extended_metadata_context(metadata: dict) -> dict:
    context = {
        "description": metadata["description"],
        "tags": metadata["tags"],
        "chapters": [
            {
                "title": chapter["title"],
                "start_label": format_duration(chapter["start_seconds"]) or "0:00",
            }
            for chapter in metadata["chapters"]
        ],
        "duration": format_duration(metadata["duration"]),
        "view_count": format_views(metadata["view_count"]),
        "like_count": format_views(metadata["like_count"]),
        "comment_count": format_views(metadata["comment_count"]),
        "uploader": metadata["uploader"],
    }
    # Counts that do not format (not a number) are not content either.
    context["has_content"] = any(
        context[key]
        for key in ("description", "tags", "chapters", "view_count", "like_count", "comment_count")
    )
    return context


def video_detail_context(detail: VideoDetail, back_path: str) -> dict:
    video = detail.video
    styles = detail.category_label_styles
    llm_provider_label = get_llm_provider_display_label()
    return {
        **detail.documents,
        "video": video,
        "category_options": styles,
        "category_option_labels": [style["label"] for style in styles],
        "category_style_map": category_style_map(styles),
        "extended_metadata": extended_metadata_context(detail.metadata),
        "vtt_content": detail.subtitles_vtt,
        "sponsor_segments": [
            {
                "category_label": SPONSOR_SEGMENT_CATEGORY_LABELS.get(row.category, row.category),
                "start_seconds": row.start_seconds,
                "start_label": format_duration(row.start_seconds) or "0:00",
                "end_label": format_duration(row.end_seconds) or "0:00",
            }
            for row in detail.sponsor_segments
        ],
        "resume_positions": detail.resume_positions,
        "sponsor_skip_payload": {
            "enabled": detail.sponsor_skip_enabled,
            "segments": detail.skip_segments,
        },
        "back_path": back_path,
        "back_label": back_label(back_path),
        "video_playlist_links": [
            {"playlist": item.playlist, "item_id": item.id} for item in video.playlist_items
        ],
        "all_playlists": detail.all_playlists,
        "llm_provider_label": llm_provider_label,
        "chat_widget_config": {
            "defaultScope": "video",
            "llmProviderLabel": llm_provider_label,
            "scopes": {
                "video": {
                    "askUrl": f"/videos/{video.id}/transcript/chat",
                    "clearUrl": f"/videos/{video.id}/transcript/chat/clear",
                    "jobUrlTemplate": f"/videos/{video.id}/transcript/jobs/" + "{job_id}",
                    "placeholder": "Discuter du contenu",
                    "messages": detail.documents["chat_messages"],
                },
            },
        },
    }
