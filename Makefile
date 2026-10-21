.PHONY: uninstall install test lint format compose-config ci up down logs migrate demo css docs-dev docs-build upgrade-ytdlp previews previews-down

# Shell environment first, then MEDIA_HOST_ROOT from .env, then the default.
MEDIA_HOST_ROOT ?= $(shell sed -n 's/^MEDIA_HOST_ROOT=//p' .env 2>/dev/null | tail -n1 | tr -d "\"'")
ifeq ($(strip $(MEDIA_HOST_ROOT)),)
MEDIA_HOST_ROOT := $(CURDIR)/.local/media/YouTube
endif
export MEDIA_HOST_ROOT

install:
	uv sync --python 3.14 --extra dev

test:
	uv run --python 3.14 --extra dev pytest

lint:
	uv run --python 3.14 --extra dev ruff check back front tests alembic
	uv run --python 3.14 --extra dev ruff format --check back front tests alembic

format:
	uv run --python 3.14 --extra dev ruff check --fix back front tests alembic
	uv run --python 3.14 --extra dev ruff format back front tests alembic

compose-config:
	docker compose config
	docker compose -f docker-compose.docs.yml config
	PREVIEW_PR=0 PREVIEW_PORT=9000 PREVIEW_SRC=. docker compose -f docker-compose.preview.yml config
	RATON_REPO=. docker compose -f docker-compose.previews.yml config

css:
	./scripts/build_css.sh

docs-dev:
	cd docs-site && npm ci && npm run dev

docs-build:
	docker build -f docs-site/Dockerfile -t raton-docs:latest .

ci: css lint test compose-config

up:
	mkdir -p "$(MEDIA_HOST_ROOT)" "$${LOG_HOST_DIR:-.local/logs}"
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

# The page that deploys the PR previews (scripts/previews.py), in its own container (docker-compose.previews.yml).
# The gh token of the host lets it list the PRs; a GH_TOKEN in the environment or in .env wins.
previews:
	@token="$${GH_TOKEN:-$$(gh auth token 2>/dev/null || true)}"; \
	if [ -n "$$token" ]; then export GH_TOKEN="$$token"; fi; \
	RATON_REPO="$(CURDIR)" docker compose -p raton-previews -f docker-compose.previews.yml up --build -d
	@echo "Page des previews sur http://$$(RATON_REPO="$(CURDIR)" docker compose -p raton-previews -f docker-compose.previews.yml port previews 8999 | sed 's/^0\.0\.0\.0:/localhost:/')"

# Stops the page only: the previews it started keep running (Retirer on the page, or scripts/preview.sh down).
previews-down:
	RATON_REPO="$(CURDIR)" docker compose -p raton-previews -f docker-compose.previews.yml down

uninstall:
	./scripts/uninstall.sh $(ARGS)
