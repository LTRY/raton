.PHONY: uninstall install test lint format compose-config ci up down logs migrate demo css docs-dev docs-build upgrade-ytdlp

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
	uv run --python 3.14 --extra dev ruff check app tests alembic
	uv run --python 3.14 --extra dev ruff format --check app tests alembic

format:
	uv run --python 3.14 --extra dev ruff check --fix app tests alembic
	uv run --python 3.14 --extra dev ruff format app tests alembic

compose-config:
	docker compose config
	docker compose -f docker-compose.docs.yml config

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
	DATABASE_URL=sqlite+pysqlite:///.local/raton.db MEDIA_ROOT="$(MEDIA_HOST_ROOT)" APP_AUTO_CREATE_TABLES=true uv run --python 3.14 uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

uninstall:
	./scripts/uninstall.sh $(ARGS)
