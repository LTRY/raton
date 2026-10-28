"""The ops.toml at the root is the contract Raton gives the ops tool (ops/docs/outil-ops.md)."""

from ops import config as ops_config


def test_repository_ops_toml_matches_the_scripts_it_names():
    config = ops_config.load()

    assert config.project_name == "Raton"
    for script in (config.deploy_script, config.previews_script):
        assert (ops_config.REPO / script).is_file()
    assert (ops_config.REPO / ".claude" / "skills" / config.review_skill / "SKILL.md").is_file()
