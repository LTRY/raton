#!/usr/bin/env bash
# `make demo`: the back (API, port 8001) on a local sqlite database, and the front (pages, port
# 8000) calling it, both reloading on code changes. Ctrl-C stops both.
set -euo pipefail

media_root="${1:-$PWD/.local/media/YouTube}"
cd "$(dirname "$0")/.."
mkdir -p .local "$media_root"

DATABASE_URL=sqlite+pysqlite:///.local/raton.db MEDIA_ROOT="$media_root" APP_AUTO_CREATE_TABLES=true \
  uv run --python 3.14 uvicorn back.main:app --host 127.0.0.1 --port 8001 --reload --reload-dir back &
back_pid=$!
trap 'kill "$back_pid" 2>/dev/null || true' EXIT

RATON_API_URL=http://127.0.0.1:8001 \
  uv run --python 3.14 uvicorn front.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir front
