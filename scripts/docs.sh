#!/usr/bin/env bash
# Rebuild and (re)start the LAN documentation site from the main checkout. Run by hand.
set -euo pipefail

DIR="${RATON_DIR:?RATON_DIR must point at the main checkout}"

docker compose -p raton-docs -f "$DIR/docker-compose.docs.yml" --project-directory "$DIR" up --build -d
