import json
from pathlib import Path


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
