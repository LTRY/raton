"""Reading a `.vtt` subtitles file as the lines of the transcript, each with its start time."""

from dataclasses import dataclass
from pathlib import Path

import webvtt


@dataclass(frozen=True)
class TranscriptLine:
    start_seconds: float
    text: str


def _start_seconds(caption: webvtt.Caption) -> float:
    start = caption.start_time
    return start.hours * 3600 + start.minutes * 60 + start.seconds + start.milliseconds / 1000


def dedupe_consecutive_lines(lines: list[TranscriptLine]) -> list[TranscriptLine]:
    # YouTube's auto-captions roll: each cue repeats the previous cue's line. A repeated line keeps
    # the start of the cue it first appeared in.
    deduped: list[TranscriptLine] = []
    previous = ""
    for line in lines:
        normalized = " ".join(line.text.split()).casefold()
        if normalized and normalized != previous:
            deduped.append(line)
        previous = normalized
    return deduped


def read_transcript_lines(subtitle_path: Path) -> list[TranscriptLine]:
    """The lines of `transcript.txt`, as written from this `.vtt` file, with their start times.

    Raises what `webvtt` raises on an unreadable file.
    """
    lines = [
        TranscriptLine(_start_seconds(caption), text.strip())
        for caption in webvtt.read(str(subtitle_path))
        for text in caption.text.splitlines()
        if text.strip()
    ]
    return dedupe_consecutive_lines(lines)
