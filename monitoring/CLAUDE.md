# CLAUDE.md — the monitoring tool

Loaded when you work under `monitoring/`. The root `CLAUDE.md` still applies (branch, `make ci`, pull request, comments, language); this file only adds what is specific to this tool. Exceptions to the root: the glossary of `docs/spec/20-glossaire.md` is Raton's, not this tool's, and PR titles of this folder take the `[MONITORING]` tag.

## What it is

A tool that watches one project and shows what it finds on its own page: today the daily log review (Claude Code runs the project's `review-logs` skill). It is meant to grow with other reports (RAG costs, functional metrics of the application), and it is separate from `ops/` on purpose: `ops/` acts on the infrastructure (previews, deploy) and has no Claude dependency; this tool observes and holds the Anthropic API key.

- Everything that names the project comes from the project's `monitoring.toml` (`monitoring/config.py`). A new project-specific value is a new key there, with a default.
- Standard library only, no dependency: the container has no virtualenv.
- No import of `back/`, `front/`, `mcp_server/`, `scripts/` or `ops/`, and no project name in the code (`tests/test_code_structure.py` checks it). It never reads the project's database: a metric comes from the project's `/api` over HTTP, or from its journal files.
- For now it is kept as generic as is cheap, not at the price of speed: the split from Raton (a core and per-project reports) comes later. `monitoring/server.py` repeats the token and origin checks of `ops/server.py` instead of importing them, because the two tools do not import each other.

## Layout

- `monitoring/*.py`: the package (`config`, `render`, `review`, `server`), run from the project's root as `python -m monitoring.server`.
- `monitoring/tests/`: its tests, run by the root `make test`.
- `monitoring/docs/outil-monitoring.md`: its spec (frontmatter `title:` equal to the first `# ` heading, French).
- `monitoring/pyproject.toml`: scopes the lint rules; the tool has no build and no dependency.

## Traps

- The container's `CMD` is frozen in the image: renaming the entry point needs a `make monitoring` rebuild by the user before it starts again.
- The repository is mounted at `/project` and the tool's code is read from that mount, not from the image: a merge changes the tool on the next start of the container, not its image.
