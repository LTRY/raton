.PHONY: uninstall install test lint format compose-config ci up down logs migrate demo css docs-dev docs-build upgrade-ytdlp previews

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

# The page that deploys the PR previews (scripts/previews.py), on the interface of APP_BIND in .env.
previews:
	PREVIEWS_BIND="$${PREVIEWS_BIND:-$$(sed -n 's/^APP_BIND=//p' .env 2>/dev/null | tail -n1 | tr -d "\"'")}" \
	  uv run --python 3.14 python scripts/previews.py

uninstall:
	./scripts/uninstall.sh $(ARGS)
