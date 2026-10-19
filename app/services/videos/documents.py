"""The text files written next to a fiche's transcript: notes, summaries, questions, chat.

Their names are fixed relative to `transcript.txt`; this module is the only one that knows them.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import local_media_path
from app.models.video import Video

NOTES_FILE = "transcript.notes.txt"
SUMMARY_FILE = "transcript.summary.txt"
SHORT_SUMMARY_FILE = "transcript.summary_short.txt"
QUESTIONS_FILE = "transcript.questions.txt"
CHAT_FILE = "transcript.chat.json"


def get_transcript_paths(video: Video) -> tuple[Path, Path, Path]:
    """(transcript, chat, notes) paths; ValueError when the fiche has no transcript file."""
    if not video.transcript_path:
        raise ValueError("Aucun transcript n'est disponible.")
    transcript_path = local_media_path(video.transcript_path)
    if not transcript_path.is_file():
        raise ValueError("Le fichier transcript est introuvable.")
    return (
        transcript_path,
        transcript_path.with_name(CHAT_FILE),
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


def read_transcript_documents(video: Video) -> dict:
    """Every document of the fiche that exists on disk; None (or empty) for the others."""
    transcript = None
    notes_transcript = None
    summary_transcript = None
    short_summary = None
    suggested_questions: list[str] = []
    chat_messages = []
    if video.transcript_path:
        path = local_media_path(video.transcript_path)
        if path.is_file():
            transcript = path.read_text(encoding="utf-8", errors="replace")
            notes_path = path.with_name(NOTES_FILE)
            summary_path = path.with_name(SUMMARY_FILE)
            summary_short_path = path.with_name(SHORT_SUMMARY_FILE)
            questions_path = path.with_name(QUESTIONS_FILE)
            if notes_path.is_file():
                notes_transcript = notes_path.read_text(encoding="utf-8", errors="replace")
            if summary_path.is_file():
                summary_transcript = summary_path.read_text(encoding="utf-8", errors="replace")
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
            chat_messages = load_chat(path.with_name(CHAT_FILE))
    return {
        "transcript": transcript,
        "notes_transcript": notes_transcript,
        "summary_transcript": summary_transcript,
        "short_summary": short_summary,
        "suggested_questions": suggested_questions,
        "display_transcript": transcript,
        "chat_messages": chat_messages,
    }


def write_generated_documents(video: Video, generated: dict) -> None:
    """Write the notes, summaries and questions an LLM generated, and store its analysis.

    The caller commits `video.ai_analysis_json`.
    """
    transcript_path, _, notes_path = get_transcript_paths(video)
    notes_path.write_text(generated["notes_text"], encoding="utf-8")
    transcript_path.with_name(SUMMARY_FILE).write_text(generated["summary_full"], encoding="utf-8")
    transcript_path.with_name(SHORT_SUMMARY_FILE).write_text(
        generated["summary_short"], encoding="utf-8"
    )
    transcript_path.with_name(QUESTIONS_FILE).write_text(
        "\n".join(generated["summary_questions"]), encoding="utf-8"
    )
    analysis = generated["analysis"]
    analysis["generated_at"] = datetime.now(UTC).isoformat()
    video.ai_analysis_json = json.dumps(analysis, ensure_ascii=False)


def append_transcript_chat(video: Video, question: str, answer: str) -> None:
    _, chat_path, _ = get_transcript_paths(video)
    messages = load_chat(chat_path)
    messages.extend(
        [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    )
    save_chat(chat_path, messages)


def clear_transcript_chat(video: Video) -> None:
    """Forget the fiche's chat; nothing to do when it has no transcript."""
    try:
        _, chat_path, _ = get_transcript_paths(video)
    except ValueError:
        return
    chat_path.unlink(missing_ok=True)
