# syntax=docker/dockerfile:1
#
# Four images from one file: `back` (the API, the scheduler, ffmpeg), `front` (the pages), `mcp` (the MCP server)
# and `ops` (the previews page and the daily log review).
# docker-compose.yml builds each with its `target`.

# Compiles front/static/css/app.css with the Tailwind standalone CLI (no
# Node/npm) so the front image ships a ready-to-serve stylesheet and never
# needs internet access at container runtime. See scripts/build_css.sh.
FROM debian:bookworm-slim AS css-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/build_css.sh scripts/build_css.sh
COPY front/static/css/tailwind.input.css front/static/css/tailwind.input.css
COPY front/templates front/templates
# build_css.sh keeps the Tailwind binary in .local/bin: the cache mount
# avoids re-downloading it every time a template changes.
RUN --mount=type=cache,target=/app/.local/bin ./scripts/build_css.sh

# Resolves the Python dependencies from uv.lock into /app/.venv. Only the
# virtualenv is copied to the final images: uv and the build caches stay here.
FROM python:3.14-slim AS deps

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /bin/uv

# Dependencies only, from uv.lock, in their own layer: it is rebuilt only
# when pyproject.toml/uv.lock change, never on a code change. The cache
# mount keeps downloaded wheels across dependency changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# What both images share: the virtualenv and an unprivileged user.
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/raton \
    PATH="/app/.venv/bin:$PATH"

# The app runs unprivileged. On Linux, bind-mounted media/log folders must be
# writable by this uid: build with `--build-arg APP_UID=$(id -u)` if yours differs.
ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --gid "$APP_GID" raton \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home --shell /usr/sbin/nologin raton

WORKDIR /app
COPY --from=deps --chown=raton:raton /app/.venv /app/.venv

FROM base AS back

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /media/youtube /var/log/raton \
    && chown raton:raton /media/youtube /var/log/raton
COPY --chown=raton:raton alembic.ini ./
COPY --chown=raton:raton alembic ./alembic
COPY --chown=raton:raton back ./back
USER raton

EXPOSE 8001
CMD ["sh", "-c", "alembic upgrade head && uvicorn back.main:app --host 0.0.0.0 --port 8001"]

FROM base AS front

COPY --chown=raton:raton front ./front
COPY --from=css-builder --chown=raton:raton /app/front/static/css/app.css front/static/css/app.css
USER raton

EXPOSE 8000
CMD ["uvicorn", "front.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS mcp

COPY --chown=raton:raton mcp_server ./mcp_server
USER raton

EXPOSE 8002
CMD ["python", "-m", "mcp_server"]

# The operations container: runs as root on purpose, it drives the host's Docker through the
# mounted socket (previews, deploy of main) and runs the daily log review with Claude Code.
# It carries no Raton dependency: the repository is mounted at the host's own path (see the `ops`
# service of docker-compose.yml), and the page and the review use the standard library only.
FROM python:3.14-slim AS ops

ENV PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gh jq make tzdata \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI with the compose and buildx plugins, as in the official docker image.
COPY --from=docker:28-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:28-cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

# Claude Code CLI, for the review-logs skill (scripts/ops_review.py).
RUN curl -fsSL https://claude.ai/install.sh | bash

# The repository belongs to the host user, not to root; GH_TOKEN (env) authenticates git over HTTPS.
# The image has no ssh client nor keys: an SSH origin of the host checkout (git@github.com:...)
# is fetched over HTTPS instead, without touching the checkout's own config.
RUN git config --global --add safe.directory '*' \
    && git config --global credential.helper '!gh auth git-credential' \
    && git config --global url.'https://github.com/'.insteadOf 'git@github.com:' \
    && git config --global --add url.'https://github.com/'.insteadOf 'ssh://git@github.com/'

WORKDIR /app
EXPOSE 8999
CMD ["sh", "-c", "[ -n \"$RATON_REPO\" ] || { echo 'RATON_REPO is empty: start it with make previews' >&2; exit 1; }; cd \"$RATON_REPO\" && exec python -m scripts.previews --host 0.0.0.0 --scheduler"]
