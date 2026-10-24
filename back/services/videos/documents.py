"""The files written next to a fiche: `metadata.json`, and next to its transcript the notes,
summaries, questions and each user's chat.

The transcript files' names are fixed relative to `transcript.txt`; this module is the only one
that knows them. Notes, summaries and questions are shared; the chat is per user
(`chat_file_name`).
"""

import json
from pathlib import Path

from back.core.config import local_media_path
from back.models.video import Video

NOTES_FILE = "transcript.notes.txt"
SHORT_SUMMARY_FILE = "transcript.summary_short.txt"
QUESTIONS_FILE = "transcript.questions.txt"
CHAT_FILE = "transcript.chat.json"
# The chat of the user who held the data before users existed (the migration's first user)
# keeps the original file name, so their discussions stay where they were.
LEGACY_CHAT_USER_ID = 1


def chat_file_name(user_id: int) -> str:
    return CHAT_FILE if user_id == LEGACY_CHAT_USER_ID else f"transcript.chat.{user_id}.json"


def read_video_metadata(video: Video) -> dict:
    """The fiche's metadata.json as yt-dlp wrote it; {} when missing or unreadable.

    A ~140 KB file: read it for one fiche, never for every row of a list.
    """
    if not video.metadata_path:
        return {}
    path = local_media_path(video.metadata_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return {}
    return data if isinstance(data, dict) else {}


def transcript_file(video: Video) -> Path:
    """The fiche's `transcript.txt`; ValueError when it has none."""
    if not video.transcript_path:
        raise ValueError("Aucun transcript n'est disponible.")
    transcript_path = local_media_path(video.transcript_path)
    if not transcript_path.is_file():
        raise ValueError("Le fichier transcript est introuvable.")
    return transcript_path


def get_transcript_paths(video: Video, user_id: int) -> tuple[Path, Path, Path]:
    """(transcript, the user's chat, notes) paths; ValueError when the fiche has no transcript
    file."""
    transcript_path = transcript_file(video)
    return (
        transcript_path,
        transcript_path.with_name(chat_file_name(user_id)),
        transcript_path.with_name(NOTES_FILE),
    )


def load_chat(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return []
    return [
        message
        for message in data
        if isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ]


def save_chat(path: Path, messages: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def read_transcript_documents(video: Video, user_id: int) -> dict:
    """Every document of the fiche that exists on disk, with the user's chat; None (or empty)
    for the others."""
    transcript = None
    notes_transcript = None
    short_summary = None
    suggested_questions: list[str] = []
    chat_messages = []
    if video.transcript_path:
        path = local_media_path(video.transcript_path)
        if path.is_file():
            transcript = path.read_text(encoding="utf-8", errors="replace")
            notes_path = path.with_name(NOTES_FILE)
            summary_short_path = path.with_name(SHORT_SUMMARY_FILE)
            questions_path = path.with_name(QUESTIONS_FILE)
            if notes_path.is_file():
                notes_transcript = notes_path.read_text(encoding="utf-8", errors="replace")
            if summary_short_path.is_file():
                short_summary = summary_short_path.read_text(encoding="utf-8", errors="replace")
            if questions_path.is_file():
                suggested_questions = [
                    line.strip()
                    for line in questions_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if line.strip()
                ]
            chat_messages = load_chat(path.with_name(chat_file_name(user_id)))
    return {
        "transcript": transcript,
        "notes_transcript": notes_transcript,
        "short_summary": short_summary,
        "suggested_questions": suggested_questions,
        "display_transcript": transcript,
        "chat_messages": chat_messages,
    }


def write_generated_documents(video: Video, generated: dict) -> None:
    """Write the notes, summaries and questions an LLM generated."""
    transcript_path = transcript_file(video)
    transcript_path.with_name(NOTES_FILE).write_text(generated["notes_text"], encoding="utf-8")
    transcript_path.with_name(SHORT_SUMMARY_FILE).write_text(
        generated["summary_short"], encoding="utf-8"
    )
    transcript_path.with_name(QUESTIONS_FILE).write_text(
        "\n".join(generated["summary_questions"]), encoding="utf-8"
    )


def append_transcript_chat(video: Video, user_id: int, question: str, answer: str) -> None:
    _, chat_path, _ = get_transcript_paths(video, user_id)
    messages = load_chat(chat_path)
    messages.extend(
        [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    )
    save_chat(chat_path, messages)


def clear_transcript_chat(video: Video, user_id: int) -> None:
    """Forget the user's chat on the fiche; nothing to do when it has no transcript."""
    try:
        _, chat_path, _ = get_transcript_paths(video, user_id)
    except ValueError:
        return
    chat_path.unlink(missing_ok=True)
