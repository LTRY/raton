"""The library chat widget of the home page: what it shows before its first `/api/chat` call."""

from sqlalchemy.orm import Session

from app.services.common.settings import get_llm_provider_display_label
from app.services.library_chat.history import chat_messages, total_video_count
from app.services.rag.retrieval import count_indexed_videos

# The requests the composer's menu offers; picking one pre-fills the question.
LIBRARY_CHAT_SUGGESTIONS = [
    {"label": "Trouver une chaîne", "prompt": "Quelles chaînes parlent de "},
    {"label": "Trouver une vidéo", "prompt": "Trouve les vidéos sur "},
    {"label": "Interroger mes notes", "prompt": "Que disent mes vidéos sur "},
    {"label": "Ajouter une chaîne YouTube", "prompt": "Ajoute la chaîne de "},
]


def library_chat_scope_config(db: Session) -> dict:
    indexed = count_indexed_videos(db)
    total = total_video_count(db)
    coverage_note = None
    if total:
        coverage_note = (
            f"{indexed} vidéo{'s' if indexed > 1 else ''} indexée{'s' if indexed > 1 else ''} sur {total} "
            "pour la recherche dans les notes (une vidéo devient indexée quand ses notes structurées sont générées)."
        )
    return {
        "chatUrl": "/api/chat",
        "placeholder": "Demander…",
        "suggestions": LIBRARY_CHAT_SUGGESTIONS,
        "messages": chat_messages(db),
        "coverageNote": coverage_note,
    }


def library_chat_widget_config(db: Session) -> dict:
    return {
        "defaultScope": "library",
        "llmProviderLabel": get_llm_provider_display_label(),
        "scopes": {"library": library_chat_scope_config(db)},
    }
