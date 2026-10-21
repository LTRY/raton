"""API JSON as template-friendly objects.

Templates read `card.title`; on a dict Jinja would first find the dict's own methods
(`page.items` is `dict.items`), so JSON objects become `Record`s. ISO date-times
(`2026-10-21T08:30:00...`, how the API writes every `datetime`) come back as `datetime`, the type
the formatting helpers take; a plain date stays text.
"""

import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any


class Record(SimpleNamespace):
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _value(value: Any) -> Any:
    if isinstance(value, str) and ISO_DATETIME.match(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return record(value)


def record(data: Any) -> Any:
    if isinstance(data, dict):
        return Record(**{key: _value(value) for key, value in data.items()})
    if isinstance(data, list):
        return [record(item) for item in data]
    return data
