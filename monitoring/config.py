"""Settings of the monitoring tool, read from `monitoring.toml` at the repository root.

Standard library only, like the page and the review that use it. A missing key falls back to the
default below, so a project only writes what differs. Spec:
monitoring/docs/outil-monitoring.md, section "Configuration de l'outil monitoring".
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The project the tool watches: MONITORING_REPO when set (the container mounts it elsewhere than
# the tool's own checkout), else the repository this package sits in.
REPO = Path(os.environ.get("MONITORING_REPO") or Path(__file__).resolve().parent.parent)
CONFIG_PATH = REPO / "monitoring.toml"


@dataclass(frozen=True)
class MonitoringConfig:
    project_name: str = "Projet"
    review_skill: str = "review-logs"
    review_allowed_tools: tuple[str, ...] = field(default=("Read", "Skill"))
    review_hour: int = 8
    review_hours: int = 24
    review_model: str = "sonnet"
    review_max_usd: float = 1.0


def parse(data: dict) -> MonitoringConfig:
    """Build the settings from a parsed `monitoring.toml`; absent keys keep the defaults."""
    default = MonitoringConfig()
    project, review = data.get("project", {}), data.get("review", {})
    return MonitoringConfig(
        project_name=project.get("name", default.project_name),
        review_skill=review.get("skill", default.review_skill),
        review_allowed_tools=tuple(review.get("allowed_tools", default.review_allowed_tools)),
        review_hour=int(review.get("hour", default.review_hour)),
        review_hours=int(review.get("hours", default.review_hours)),
        review_model=review.get("model", default.review_model),
        review_max_usd=float(review.get("max_usd", default.review_max_usd)),
    )


def load(path: Path = CONFIG_PATH) -> MonitoringConfig:
    """The settings of `path`; the defaults when the file does not exist."""
    if not path.is_file():
        return MonitoringConfig()
    return parse(tomllib.loads(path.read_text()))


CONFIG = load()
