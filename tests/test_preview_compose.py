import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _services(compose_file: str) -> dict[str, str]:
    """Top-level services of a compose file with their raw block, without a YAML dependency."""
    text = "\n" + (ROOT / compose_file).read_text()
    body = text.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    blocks = re.split(r"(?m)^  (?=[\w-]+:\s*$)", body)
    return {block.split(":", 1)[0]: block for block in blocks if re.match(r"[\w-]+:\s*\n", block)}


def test_a_preview_service_on_the_real_network_never_shares_a_name_with_the_real_stack():
    # Compose aliases a service by its name on every network it joins: a preview `api` on the
    # real network would answer the real front's `http://api:8001` (read-only media mount).
    real_names = set(_services("docker-compose.yml"))
    joined = {
        n for n, block in _services("docker-compose.preview.yml").items() if "- real" in block
    }
    assert joined, "the preview back is expected to join the real network"
    assert not joined & real_names


def test_the_real_stack_comes_back_by_itself_after_a_reboot_or_a_crash():
    services = _services("docker-compose.yml")
    for name in ("db", "api", "app", "mcp"):
        assert "restart: unless-stopped" in services[name], name
    # The pages wait for the back to answer, not just to exist; `ops` and `monitoring` stay behind
    # their profiles and are not part of this.
    assert "condition: service_healthy" in services["app"]
    assert "healthcheck:" in services["api"]


def test_previews_never_restart_on_their_own():
    assert "restart:" not in (ROOT / "docker-compose.preview.yml").read_text()
