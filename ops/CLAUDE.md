# CLAUDE.md — the ops tool

Loaded when you work under `ops/`. The root `CLAUDE.md` still applies (branch, `make ci`, pull request, comments, language); this file only adds what is specific to this tool. Exceptions to the root: the glossary of `docs/spec/20-glossaire.md` is Raton's, not this tool's, and PR titles of this folder take the `[OPS]` tag.

## What it is

A standalone tool that serves one project at a time: the previews page, the deploy of the main branch and the daily log review. It is meant to be reused by other projects, so it must not know Raton.

- Everything that names the project comes from the project's `ops.toml` (`ops/config.py`). A new project-specific value is a new key there, with a default, never a constant in the code.
- The project provides the contract: `ops.toml`, a previews script (`up|rebase|down|sweep|list`), a deploy script, and a way to start the tool. The contract is in `ops/docs/outil-ops.md`; changing it changes every project that uses the tool, so write the change in the spec first.
- Standard library only, no dependency: the container has no virtualenv.
- No import of `back/`, `front/`, `mcp_server/` or `scripts/`, and no project name in the code (`tests/test_code_structure.py` checks both). The project's own scripts are called by path, never imported.

## Layout

- `ops/*.py`: the package (`config`, `jobs`, `render`, `review`, `server`, `deploy_lock`), run from the project's root as `python -m ops.server`.
- `ops/tests/`: its tests, run by the root `make test`.
- `ops/docs/outil-ops.md`: its spec (frontmatter `title:` equal to the first `# ` heading, French, like `docs/spec/`).
- `ops/pyproject.toml`: scopes the lint rules; the tool has no build and no dependency.

## Traps

- The container's `CMD` is frozen in the image: renaming the entry point needs a `make previews` rebuild by the user before it starts again.
- The repository is mounted at the host's own path (`OPS_REPO`) and the tool's code is read from that mount, not from the image: a merge changes the tool on the next start of the container, not its image.
