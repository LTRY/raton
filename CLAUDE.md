# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is the single LLM instruction file for this repo — it applies no matter which LLM/tool is editing this codebase.

## Specification first

Before changing Raton, read the relevant files under `docs/spec/`. Every behavior change must update the code and the spec in the same change. If the code and spec disagree, treat the work as incomplete. Use the vocabulary of `docs/spec/20-glossaire.md` (cloche, fiche, Nouveautés, Vu, purge, DB...) in code names, specs, UI strings, PR text and replies to the user — no synonyms — and update it in the same change when a term's meaning moves. Spec files need a frontmatter `title:` equal to their first `# ` heading (`tests/test_docs_spec.py` checks it).

## Workflow: branch, `make ci`, pull request

Changes reach `main` only through pull requests on the GitHub repo (`LTRY/raton`); `.github/workflows/ci.yml` runs `make ci`, the docs image build and a secret scan on each one. Agents do not deploy: merging a PR deploys nothing, the user deploys by hand with `make up`. Spec: `docs/spec/04-configuration-et-deploiement.md`.

1. Work on a dedicated branch, never directly on `main`. Start every new task from an up-to-date `origin/main`: `git fetch origin main` first, then branch from (or fast-forward to) `origin/main`. The `SessionStart` hook in `.claude/settings.json` (`.claude/hooks/sync-origin-main.sh`) does this automatically at session start when the branch has no commits of its own and no modified tracked files; when a new task starts mid-session, do it by hand.
2. Do the task: implement it and commit on the branch.
3. Run `make ci` before opening the PR. If it fails, fix the issue and re-run it — never open a PR on a red `make ci`.
4. Push the branch and open a pull request against `main` (`gh pr create`), without waiting to be asked. Don't merge the branch into `main` locally.

Do **not** run `make up`, `make uninstall` or `scripts/docs.sh` as part of a task: they act on the user's Docker stack. Deployment is done by the user by hand.

Migrations: write the revision by hand in `alembic/versions/`, named `NNNN_short_slug` (`down_revision` = the previous id, working `downgrade()`), id of 32 characters at most (`tests/test_migration_revisions.py`). The PR title takes `[DB]`.

### Pull request titles

Prefix the title with scope tags, then an imperative English summary: `[FRONT] Stats: link channel names to their channel page`. Tags: `[FRONT]` (templates, CSS, JS, visible UI), `[BACK]` (routes, services, models, scheduler, API), `[DB]` (migration/schema), `[CI]` (workflows, `scripts/`, Makefile, Docker), `[DOCS]` (spec/CLAUDE.md/comments only, no behavior change). Front and back together: `[FRONT][BACK]`, no space. A fix starts its summary with `Fix`; no `feat:`/`fix:` prefixes; 72 characters max, no trailing period. For a `[FRONT]` PR, the description includes the screenshots (see "Show screenshots"). `scripts/check_pr_title.py` (workflow `pr-title.yml`) enforces these rules. Fill in `.github/pull_request_template.md`. Full rules: `docs/spec/04-configuration-et-deploiement.md`, section "Conventions de nommage des PR".

## Show screenshots

Whenever a change is visible in the UI, show the user screenshots of the result in the conversation — don't just describe it. Do the same to illustrate a problem: a layout bug, a broken page or an unexpected state is clearer shown than explained. Capture both a desktop and a phone width when the layout differs.

How: `scripts/screenshot.sh [path] [out-dir]` runs the app on a throwaway sqlite database seeded with the demo data (never the user's real data), captures `desktop.png` (1280px) and `phone.png` (390px, full page) with headless Playwright, prints the page's `scrollWidth`/`clientWidth` at both widths, then stops the server. For a page that needs other rows, seed them the same way (`app/services/demo_seed.py`). `curl` alone cannot catch layout bugs.

## Design rule: no horizontal page scroll on iPhone

On a phone (iPhone Safari first), no page may move sideways: the page itself must never be wider than the screen, and a swipe must never reveal blank space on the right. Applies to every new or edited template, component and CSS rule.

- Content that is wider than the screen (carousels, tables, code blocks, filter chips) scrolls **inside its own container** (`overflow-x: auto` on that container), never the page.
- A grid or flex child that holds such content, or a `select`/`input`, needs `min-width: 0` (grid: `minmax(0, 1fr)`) — otherwise it stretches its parent past the viewport.
- Long unbroken strings (URLs, titles, file names) wrap (`overflow-wrap: anywhere`) or truncate; no fixed pixel widths larger than ~320px outside a scroll container.
- `html`/`body` carry `overflow-x: clip` as a last-resort net (`tests/test_page_overflow_css.py` guards it), **not** as the fix: find the element that overflows and constrain it.
- Check with `scripts/screenshot.sh <path>` before opening the PR: it must print `ok` (`scrollWidth` equal to `clientWidth`) at 390px.

Spec: `docs/spec/11-interface-html.md`, section "Base".

## Design rule: pages must load fast

A page must not feel slow to open. Slowness is a bug, not a polish item: investigate the cause (measure, don't guess) before shipping a change that touches a page's data or markup.

- The number of SQL statements of a page must not grow with the library: eager-load what the template reads (`selectinload`/`joinedload`), never one lazy load per row, and never scan an ever-growing table (`download_jobs`) without a time or `LIMIT` bound.
- Don't read files from disk (`metadata.json`, transcripts) for every row of a list: only for the rows actually displayed, or store the value in a column.
- Don't load a whole table to paginate or count in Python when SQL can do it.
- Check a page that lists data against a library of a few thousand videos, not the 3-row seed; `tests/test_page_load.py` shows how to assert a statement count.

Spec: `docs/spec/11-interface-html.md`, section "Temps de chargement des pages".

## Language

- **Code comments and docstrings: English.** Write every new or edited comment in English, even in a file whose other comments are still in French. Many existing comments are in French; translate the ones you touch, but don't mass-translate a file as a side effect of an unrelated change.
- **Docs (`docs/spec/`) and user-facing strings: French** — match that when editing existing files.

## Comments

Comments must stay true when code elsewhere changes, because a stale comment misleads the next reader (human or LLM) more than a missing one.

- Comment the *why*: a reason, a constraint, a trap. Don't paraphrase what the line already says.
- Don't restate facts that are defined in another file (a router's list of routes, a function's behavior, a directory's contents) — those go stale without anyone touching the comment. Point to the source instead, or say nothing.
- When a change makes a comment or docstring wrong, fix or delete it in the same commit, including comments in other files that describe the code you changed.
- If an invariant can be checked by a test, write the test rather than a comment.

## Commands

```bash
make ci             # css + lint + test + compose-config (run before opening a PR; also run by .github/workflows/ci.yml)
make format         # ruff fix + format (also run on every edited .py by the PostToolUse hook)
make demo           # uvicorn --reload on a local sqlite db with auto-created tables (no Postgres needed)
make upgrade-ytdlp  # yt-dlp only moves when uv.lock does: the Docker image installs from the lock
```

Other targets (`install`, `test`, `lint`, `css`, `migrate`, `docs-dev`, `docs-build`, `up`...) are in the Makefile; `make up` is the deploy and is not part of the task workflow.

Single test: `uv run --python 3.14 pytest tests/test_videos.py::test_name -v`

The FastAPI app expects a reachable Postgres via `DATABASE_URL` unless you use `make demo` (sqlite, `APP_AUTO_CREATE_TABLES=true`).

## Architecture

Stack: Python 3.14, FastAPI, Jinja2 (server-rendered, no frontend framework), SQLAlchemy, Alembic, PostgreSQL 16 (Docker Compose), yt-dlp + ffmpeg, APScheduler, Anthropic API for the LLM features. The layout, data model, data flow and jobs are described in `docs/spec/03-architecture.md`, `05-modele-de-donnees.md` and `13-jobs-logs-planification.md`; the structure rules are enforced by `tests/test_code_structure.py` (no route in `app/main.py`, `app/web/shared.py` imports no other web module).

Traps:

- Tests that fake the DB session of a background job runner patch `app.services.background_jobs.SessionLocal` (each runner opens its own session).
- `video_path` and `audio_path` can coexist: always check the path columns, never `media_type` alone.
- The Docker stack ignores `DATABASE_URL`/`MEDIA_ROOT` from `.env` (the compose file hardcodes them); nothing outside Docker reads them. Spec: `04-configuration-et-deploiement.md`.

### Security model (see `docs/spec/15-securite.md`)

- Raton runs on a trusted LAN. The HTML and API routes are **intentionally unauthenticated** — not an accidental vulnerability. A change that exposes the app beyond the LAN makes authentication, CSRF, CORS/cookie review and Postgres hardening required.
- Never commit `.env`, Claude Code auth (`~/.claude/`), or `ANTHROPIC_API_KEY`.
- Redirects built from a form `next`/`return_to` go through `internal_return_path` (`app/web/shared.py`).
