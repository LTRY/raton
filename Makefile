.PHONY: uninstall install test lint format compose-config ci up up-locked down logs migrate demo css docs-dev docs-build upgrade-ytdlp previews

# Shell environment first, then MEDIA_HOST_ROOT from .env, then the default.
MEDIA_HOST_ROOT ?= $(shell sed -n 's/^MEDIA_HOST_ROOT=//p' .env 2>/dev/null | tail -n1 | tr -d "\"'")
ifeq ($(strip $(MEDIA_HOST_ROOT)),)
MEDIA_HOST_ROOT := $(CURDIR)/.local/media/YouTube
endif
export MEDIA_HOST_ROOT

# The ops container mounts the repository at this very path (see the `ops` service).
export OPS_REPO := $(CURDIR)

# Stamped on the api image (label raton.git-sha): the previews page compares it with origin/main.
export GIT_SHA := $(shell git rev-parse HEAD 2>/dev/null)

install:
	uv sync --python 3.14 --extra dev

test:
	uv run --python 3.14 --extra dev pytest

lint:
	uv run --python 3.14 --extra dev ruff check back front mcp_server ops scripts tests alembic
	uv run --python 3.14 --extra dev ruff format --check back front mcp_server ops scripts tests alembic

format:
	uv run --python 3.14 --extra dev ruff check --fix back front mcp_server ops scripts tests alembic
	uv run --python 3.14 --extra dev ruff format back front mcp_server ops scripts tests alembic

compose-config:
	docker compose config
	docker compose -f docker-compose.docs.yml config
	PREVIEW_PR=0 PREVIEW_PORT=9000 PREVIEW_SRC=. PREVIEW_DB_NAME=raton PREVIEW_DB_NETWORK=raton_default docker compose -f docker-compose.preview.yml config

css:
	./scripts/build_css.sh

docs-dev:
	cd docs-site && npm ci && npm run dev

docs-build:
	docker build -f docs-site/Dockerfile -t raton-docs:latest .

ci: css lint test compose-config

# One deploy at a time, the same lock as scripts/deploy.sh and the previews page's button
# (ops/deploy_lock.py); a deploy.sh that already holds it runs `make up` without taking it again.
up:
	python3 ops/deploy_lock.py $(MAKE) --no-print-directory up-locked

up-locked:
	mkdir -p "$(MEDIA_HOST_ROOT)" "$${LOG_HOST_DIR:-.local/logs}"
	# Before the api migrates the real DB at startup: a preview on it would keep old code there.
	./scripts/preview.sh retire-stale
	docker compose up --build -d
	# The rebuild moves the image tag, leaving the previous build as a dangling image;
	# drop those so images don't pile up. The BuildKit cache is kept (fast rebuilds).
	-docker image prune -f
	@addr=$$(docker compose port app 8000 2>/dev/null | sed 's/^0\.0\.0\.0:/localhost:/'); \
	echo "Raton is up on http://$${addr:-127.0.0.1:8000}"

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	uv run --python 3.14 alembic upgrade head

upgrade-ytdlp:
	uv lock --upgrade-package yt-dlp

demo: css
	mkdir -p .local "$(MEDIA_HOST_ROOT)"
	./scripts/demo.sh "$(MEDIA_HOST_ROOT)"

# The raton-ops container (docker-compose.yml, profile `ops`): the page that deploys the PR previews
# and main (ops/server.py, port 8999 on the interface of APP_BIND) and the daily log review.
previews:
	docker compose --profile ops up --build -d ops
	-docker image prune -f

uninstall:
	./scripts/uninstall.sh $(ARGS)
