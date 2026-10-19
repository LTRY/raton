import re
import shutil
import unicodedata
import uuid
from pathlib import Path

INVALID_FILENAME_CHARS = r'[<>:"/\\|?*\x00-\x1f]'


def sanitize_filename(value: str, max_length: int = 120) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(INVALID_FILENAME_CHARS, " ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return "untitled"
    return cleaned[:max_length].rstrip(" .")


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def remove_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def unique_sibling_path(path: Path, marker: str) -> Path:
    return path.with_name(f".{path.name}.{marker}.{uuid.uuid4().hex}")


def move_directory(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
