"""The library chat widget of the home page: its config, from `GET /api/chat`, and the user
menu of its drawer, from `GET /api/users`."""

# The requests the composer's menu offers; picking one pre-fills the question.
LIBRARY_CHAT_SUGGESTIONS = [
    {"label": "Trouver une chaîne", "prompt": "Quelles chaînes parlent de "},
    {"label": "Trouver une vidéo", "prompt": "Trouve les vidéos sur "},
    {"label": "Interroger mes notes", "prompt": "Que disent mes vidéos sur "},
    {"label": "Ajouter une chaîne YouTube", "prompt": "Ajoute la chaîne de "},
]


def library_chat_scope_config(chat: dict) -> dict:
    return {
        "chatUrl": "/api/chat",
        # Where the widget opens or deletes a discussion: `{conversationsUrl}/{id}`.
        "conversationsUrl": "/api/chat/conversations",
        "conversationId": chat["conversation_id"],
        "conversations": chat["conversations"],
        "placeholder": "Demander…",
        "suggestions": LIBRARY_CHAT_SUGGESTIONS,
        "messages": chat["messages"],
    }


def library_chat_widget_config(chat: dict, llm_provider_label: str) -> dict:
    return {
        "defaultScope": "library",
        "llmProviderLabel": llm_provider_label,
        "scopes": {"library": library_chat_scope_config(chat)},
    }
