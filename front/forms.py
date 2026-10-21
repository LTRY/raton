"""Fields of the no-JS forms, read the way the browser sends them."""


def form_list_values(value: list[str] | None) -> list[str]:
    return value if isinstance(value, list) else []


def form_text_value(value: str | None) -> str:
    return value if isinstance(value, str) else ""


def split_labels(text: str) -> list[str]:
    """The labels typed in a "custom" field, comma- or line-separated; the API normalizes them."""
    return [label.strip() for label in text.replace("\n", ",").split(",") if label.strip()]


def submitted_categories(
    preset_categories: list[str] | None, custom_categories: str | None
) -> list[str]:
    return [*form_list_values(preset_categories), *split_labels(form_text_value(custom_categories))]


def labels_text(labels: list[str]) -> str:
    """Labels as one comma-joined value (lower case, single spaces, no duplicate), the way the
    API stores them: what a hidden field carries to the next form."""
    normalized: list[str] = []
    for label in labels:
        label = " ".join(label.strip().lower().split())
        if label and label not in normalized:
            normalized.append(label)
    return ",".join(normalized)


def bell_section(section: str) -> str:
    return "shorts" if section in {"short", "shorts"} else "videos"


def bell_section_label(section: str) -> str:
    return "shorts" if section == "shorts" else "vidéos"
