"""Settings of the ops tool, read from `ops.toml` at the repository root.

Standard library only, like the page that uses it. A missing key falls back to the
default below, so a project only writes what differs. Spec:
ops/docs/outil-ops.md, section "Configuration de l'outil ops".
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# The project the tool serves: OPS_REPO when set (the ops container mounts it elsewhere than the
# tool's own checkout), else the repository this package sits in.
REPO = Path(os.environ.get("OPS_REPO") or Path(__file__).resolve().parent.parent)
CONFIG_PATH = REPO / "ops.toml"


@dataclass(frozen=True)
class OpsConfig:
    project_name: str = "Projet"
    deploy_script: str = "scripts/deploy.sh"
    deploy_branch: str = "main"
    deploy_container: str = ""
    deploy_sha_label: str = ""
    previews_script: str = "scripts/preview.sh"
    job_timeout_minutes: int = 30


def parse(data: dict) -> OpsConfig:
    """Build the settings from a parsed `ops.toml`; absent sections and keys keep the defaults."""
    default = OpsConfig()
    project, deploy = data.get("project", {}), data.get("deploy", {})
    previews, jobs = data.get("previews", {}), data.get("jobs", {})
    return OpsConfig(
        project_name=project.get("name", default.project_name),
        deploy_script=deploy.get("script", default.deploy_script),
        deploy_branch=deploy.get("branch", default.deploy_branch),
        deploy_container=deploy.get("container", default.deploy_container),
        deploy_sha_label=deploy.get("sha_label", default.deploy_sha_label),
        previews_script=previews.get("script", default.previews_script),
        job_timeout_minutes=int(jobs.get("timeout_minutes", default.job_timeout_minutes)),
    )


def load(path: Path = CONFIG_PATH) -> OpsConfig:
    """The settings of `path`; the defaults when the file does not exist."""
    if not path.is_file():
        return OpsConfig()
    return parse(tomllib.loads(path.read_text()))


CONFIG = load()
