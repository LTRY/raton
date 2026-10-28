"""The monitoring.toml at the root is the contract Raton gives the monitoring tool."""

from monitoring import config as monitoring_config


def test_repository_monitoring_toml_names_an_existing_skill():
    config = monitoring_config.load()

    assert config.project_name == "Raton"
    skill = monitoring_config.REPO / ".claude" / "skills" / config.review_skill / "SKILL.md"
    assert skill.is_file()
