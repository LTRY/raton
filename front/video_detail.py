"""The page of a fiche: labels and links around `GET /api/videos/{id}`."""

from front.formatting import format_duration, format_views


def back_label(back_path: str) -> str:
    if back_path.startswith("/playlists/"):
        return "Retour à la playlist"
    if "channel_id=" in back_path:
        return "Retour à la chaîne"
    return "Retour à la bibliothèque"


def extended_metadata_context(metadata) -> dict:
    context = {
        "description": metadata.description,
        "tags": metadata.tags,
        "chapters": [
            {
                "title": chapter.title,
                "start_label": format_duration(chapter.start_seconds) or "0:00",
            }
            for chapter in metadata.chapters
        ],
        "duration": format_duration(metadata.duration_seconds),
        "view_count": format_views(metadata.view_count),
        "like_count": format_views(metadata.like_count),
        "comment_count": format_views(metadata.comment_count),
        "uploader": metadata.uploader,
    }
    # Counts that do not format (not a number) are not content either.
    context["has_content"] = any(
        context[key]
        for key in ("description", "tags", "chapters", "view_count", "like_count", "comment_count")
    )
    return context


def video_detail_context(video, raw: dict, settings, playlists, back_path: str) -> dict:
    """`video` is the fiche as records, `raw` the same JSON (embedded as JSON in the page)."""
    styles = settings.video_category_label_styles
    sponsor_labels = {
        choice.value: choice.label for choice in settings.sponsor_segment_category_choices
    }
    documents = video.documents
    llm_provider_label = settings.llm_provider_label
    return {
        "transcript": documents.transcript,
        "notes_transcript": documents.notes,
        "short_summary": documents.short_summary,
        "suggested_questions": documents.suggested_questions,
        "quiz": raw["documents"]["quiz"],
        "display_transcript": documents.transcript,
        "video": video,
        "category_options": styles,
        "category_option_labels": [style.label for style in styles],
        "category_style_map": {style.label: style for style in styles},
        "extended_metadata": extended_metadata_context(video.metadata),
        "vtt_content": video.subtitles_vtt,
        "sponsor_segments": [
            {
                "category_label": sponsor_labels.get(segment.category, segment.category),
                "start_seconds": segment.start_seconds,
                "start_label": format_duration(segment.start_seconds) or "0:00",
                "end_label": format_duration(segment.end_seconds) or "0:00",
            }
            for segment in video.sponsor_segments
        ],
        "resume_positions": video.resume_positions,
        "sponsor_skip_payload": {
            "enabled": raw["sponsor_skip_enabled"],
            "segments": raw["skip_segments"],
        },
        "back_path": back_path,
        "back_label": back_label(back_path),
        "video_playlist_links": video.playlists,
        "all_playlists": playlists,
        "llm_provider_label": llm_provider_label,
        "chat_widget_config": {
            "defaultScope": "video",
            "llmProviderLabel": llm_provider_label,
            "scopes": {
                "video": {
                    "chatUrl": f"/api/videos/{video.id}/chat",
                    "placeholder": "Discuter du contenu",
                    "messages": raw["documents"]["chat_messages"],
                },
            },
        },
    }
