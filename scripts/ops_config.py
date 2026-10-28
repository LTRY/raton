"""Settings of the ops tool, read from `ops.toml` at the repository root.

Standard library only, like the page and the review that use it. A missing key falls back to the
default below, so a project only writes what differs. Spec:
docs/spec/04-configuration-et-deploiement.md, section "Configuration de l'outil ops".
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO / "ops.toml"


@dataclass(frozen=True)
class OpsConfig:
    project_name: str = "Projet"
    deploy_script: str = "scripts/deploy.sh"
    deploy_branch: str = "main"
    deploy_container: str = ""
    deploy_sha_label: str = ""
    previews_script: str = "scripts/preview.sh"
    review_skill: str = "review-logs"
    review_allowed_tools: tuple[str, ...] = field(default=("Read", "Skill"))
    review_hour: int = 8
    review_hours: int = 24
    review_model: str = "sonnet"
    review_max_usd: float = 1.0


def parse(data: dict) -> OpsConfig:
    """Build the settings from a parsed `ops.toml`; absent sections and keys keep the defaults."""
    default = OpsConfig()
    project, deploy = data.get("project", {}), data.get("deploy", {})
    previews, review = data.get("previews", {}), data.get("review", {})
    return OpsConfig(
        project_name=project.get("name", default.project_name),
        deploy_script=deploy.get("script", default.deploy_script),
        deploy_branch=deploy.get("branch", default.deploy_branch),
        deploy_container=deploy.get("container", default.deploy_container),
        deploy_sha_label=deploy.get("sha_label", default.deploy_sha_label),
        previews_script=previews.get("script", default.previews_script),
        review_skill=review.get("skill", default.review_skill),
        review_allowed_tools=tuple(review.get("allowed_tools", default.review_allowed_tools)),
        review_hour=int(review.get("hour", default.review_hour)),
        review_hours=int(review.get("hours", default.review_hours)),
        review_model=review.get("model", default.review_model),
        review_max_usd=float(review.get("max_usd", default.review_max_usd)),
    )


def load(path: Path = CONFIG_PATH) -> OpsConfig:
    """The settings of `path`; the defaults when the file does not exist."""
    if not path.is_file():
        return OpsConfig()
    return parse(tomllib.loads(path.read_text()))


CONFIG = load()
