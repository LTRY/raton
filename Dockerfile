# syntax=docker/dockerfile:1

# Compiles app/static/css/app.css with the Tailwind standalone CLI (no
# Node/npm) so the final image ships a ready-to-serve stylesheet and never
# needs internet access at container runtime. See scripts/build_css.sh.
FROM debian:bookworm-slim AS css-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/build_css.sh scripts/build_css.sh
COPY app/static/css/tailwind.input.css app/static/css/tailwind.input.css
COPY app/templates app/templates
# build_css.sh keeps the Tailwind binary in .local/bin: the cache mount
# avoids re-downloading it every time a template changes.
RUN --mount=type=cache,target=/app/.local/bin ./scripts/build_css.sh

# Resolves the Python dependencies from uv.lock into /app/.venv. Only the
# virtualenv is copied to the final image: uv and the build caches stay here.
FROM python:3.14-slim AS deps

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /bin/uv

# Dependencies only, from uv.lock, in their own layer: it is rebuilt only
# when pyproject.toml/uv.lock change, never on an app code change. The cache
# mount keeps downloaded wheels across dependency changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/raton \
    PATH="/app/.venv/bin:$PATH"

# The app runs unprivileged. On Linux, bind-mounted media/log folders must be
# writable by this uid: build with `--build-arg APP_UID=$(id -u)` if yours differs.
ARG APP_UID=1000
ARG APP_GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" raton \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home --shell /usr/sbin/nologin raton \
    && mkdir -p /media/youtube /var/log/raton \
    && chown raton:raton /media/youtube /var/log/raton

WORKDIR /app

COPY --from=deps --chown=raton:raton /app/.venv /app/.venv
COPY --chown=raton:raton alembic.ini ./
COPY --chown=raton:raton alembic ./alembic
COPY --chown=raton:raton app ./app
COPY --from=css-builder --chown=raton:raton /app/app/static/css/app.css app/static/css/app.css

USER raton

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
