from ops import config as ops_config
from ops import jobs as ops_jobs
from ops import render as ops_render
from ops import review as ops_review


def test_missing_keys_and_file_fall_back_to_the_defaults(tmp_path):
    assert ops_config.load(tmp_path / "absent.toml") == ops_config.OpsConfig()

    path = tmp_path / "ops.toml"
    path.write_text('[project]\nname = "Autre"\n[review]\nhour = 6\nallowed_tools = ["Read"]\n')
    config = ops_config.load(path)

    assert config.project_name == "Autre"
    assert config.review_hour == 6
    assert config.review_allowed_tools == ("Read",)
    assert config.review_skill == "review-logs"
    assert config.deploy_container == ""


def test_the_review_command_reads_the_skill_and_tools_from_the_config(monkeypatch):
    config = ops_config.parse({"review": {"skill": "check-logs", "allowed_tools": ["Read"]}})
    monkeypatch.setattr(ops_review, "CONFIG", config)

    command = ops_review.build_command(12, None, 2.0)

    assert command[3] == "/check-logs 12"
    assert command[command.index("--allowedTools") + 1 :] == ["Read"]


def test_deployed_sha_is_unknown_without_a_container_to_inspect(monkeypatch):
    monkeypatch.setattr(ops_jobs, "CONFIG", ops_config.OpsConfig())

    assert ops_jobs.deployed_sha() is None


def test_the_project_name_is_escaped_in_the_page(monkeypatch):
    monkeypatch.setattr(ops_render, "CONFIG", ops_config.OpsConfig(project_name="A<b>'c"))

    page = ops_render.render_page("nas:8999", [], {}, {}, None)

    assert "A&lt;b&gt;&#x27;c" in page
    assert "<b>" not in page
