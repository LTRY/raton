from monitoring import config as monitoring_config
from monitoring import review as monitoring_review


def test_missing_keys_and_file_fall_back_to_the_defaults(tmp_path):
    assert monitoring_config.load(tmp_path / "absent.toml") == monitoring_config.MonitoringConfig()

    path = tmp_path / "monitoring.toml"
    path.write_text('[project]\nname = "Autre"\n[review]\nhour = 6\nallowed_tools = ["Read"]\n')
    config = monitoring_config.load(path)

    assert config.project_name == "Autre"
    assert config.review_hour == 6
    assert config.review_allowed_tools == ("Read",)
    assert config.review_skill == "review-logs"


def test_the_review_command_reads_the_skill_and_tools_from_the_config(monkeypatch):
    config = monitoring_config.parse({"review": {"skill": "check-logs", "allowed_tools": ["Read"]}})
    monkeypatch.setattr(monitoring_review, "CONFIG", config)

    command = monitoring_review.build_command(12, None, 2.0)

    assert command[3] == "/check-logs 12"
    assert command[command.index("--allowedTools") + 1 :] == ["Read"]
