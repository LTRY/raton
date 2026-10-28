#!/usr/bin/env bash
# The PR previews: one throwaway Raton (back + front, demo data) per pull request, on port
# 9000 + its number. Driven by hand or by the previews page (ops/server.py).
#
#   preview.sh up <pr>     build the PR's current head and (re)start its preview
#   preview.sh down <pr>   remove the PR's preview: containers, images, worktree, DB copy
#   preview.sh list        one line per preview: <pr> <port> <commit> <container state> <db>
#   preview.sh sweep       remove the previews of the PRs that are no longer open
#   preview.sh retire-stale  remove the previews on the real DB whose migration head is not
#                          main's: run by `make up` before the deploy migrates that DB
#
# Each preview is its own compose project (raton-pr-<pr>, docker-compose.preview.yml), built
# from a git worktree of the PR's head in .local/previews/pr-<pr>. Same-repository PRs only:
# the host builds and runs the PR's code, so a fork's PR never gets one.
# Its DB is the real stack's (raton-db) when the PR has no migration to run on it, else a copy
# (database raton_pr_<pr> on the same server) that the preview migrates: scripts/preview_db.py
# decides.
# Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
set -euo pipefail

BASE_PORT=9000
DB_CONTAINER=raton-db

cd "$(dirname "$0")/.."
REPO="$PWD"

port_for() { echo $((BASE_PORT + $1)); }
worktree_for() { echo "$REPO/.local/previews/pr-$1"; }

require_pr() {
  [[ "${1:-}" =~ ^[0-9]+$ ]] || { echo "preview.sh: numéro de PR attendu, reçu '${1:-}'" >&2; exit 2; }
}

db_psql() { docker exec -i "$DB_CONTAINER" "$@"; }

# Always with the preview file: a bare `docker compose` here would load the real stack's file.
compose() {
  local pr="$1"; shift
  PREVIEW_PR="$pr" PREVIEW_PORT="$(port_for "$pr")" PREVIEW_SRC="$(worktree_for "$pr")" \
    PREVIEW_DB_NAME="${PREVIEW_DB_NAME:-raton}" PREVIEW_DB_NETWORK="${PREVIEW_DB_NETWORK:-none}" \
    docker compose -p "raton-pr-$pr" -f "$REPO/docker-compose.preview.yml" "$@"
}

cmd_up() {
  require_pr "${1:-}"
  local pr="$1" info state cross sha src address db_revision mode copy
  info="$(gh pr view "$pr" --json state,isCrossRepository --jq '.state + " " + (.isCrossRepository | tostring)')"
  state="${info%% *}"
  cross="${info#* }"
  if [ "$state" != "OPEN" ]; then
    echo "preview.sh: la PR $pr n'est pas ouverte ($state)" >&2; exit 1
  fi
  if [ "$cross" != "false" ]; then
    echo "preview.sh: la PR $pr vient d'un fork : pas de preview (son code tournerait sur cette machine)" >&2; exit 1
  fi

  git fetch -q origin "+refs/pull/$pr/head:refs/previews/pr-$pr"
  sha="$(git rev-parse "refs/previews/pr-$pr")"
  src="$(worktree_for "$pr")"
  if [ -d "$src" ]; then
    git -C "$src" checkout -q --detach --force "$sha"
  else
    mkdir -p "$(dirname "$src")"
    git worktree add -q --detach "$src" "$sha"
  fi

  if [ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" != "true" ]; then
    echo "preview.sh: $DB_CONTAINER ne tourne pas : lancez la pile réelle (make up)" >&2; exit 1
  fi
  db_revision="$(db_psql psql -U raton -d raton -tAc 'SELECT version_num FROM alembic_version')"
  mode="$(python3 "$REPO/scripts/preview_db.py" "$src/alembic/versions" "$db_revision")"
  copy="raton_pr_$pr"
  # The previous deploy's api holds connections to the copy: stop it before dropping the copy.
  compose "$pr" stop preview-api >/dev/null 2>&1 || true
  db_psql dropdb -U raton --if-exists --force "$copy"
  if [ "$mode" = copy ]; then
    echo "preview $pr : la PR a des migrations à jouer, copie de la DB dans $copy..."
    db_psql createdb -U raton "$copy"
    db_psql bash -c "set -o pipefail; pg_dump -U raton raton | psql -q -v ON_ERROR_STOP=1 -U raton $copy" >/dev/null
    export PREVIEW_DB_NAME="$copy" PREVIEW_MIGRATE=1
  else
    echo "preview $pr : aucune migration à jouer, branchée sur la DB réelle"
    export PREVIEW_DB_NAME=raton PREVIEW_MIGRATE=0
  fi
  export PREVIEW_DB_MODE="$mode"
  PREVIEW_DB_NETWORK="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$DB_CONTAINER" | cut -d' ' -f1)"
  export PREVIEW_DB_NETWORK
  echo "preview $pr : commit ${sha:0:7}, construction..."

  export PREVIEW_SHA="$sha"
  if ! compose "$pr" up -d --build --force-recreate --remove-orphans; then
    echo "preview.sh: la construction de la preview $pr a échoué" >&2; exit 1
  fi
  # The preview's port is published on the host. In the raton-ops container, loopback is the
  # container itself, so the host is reached by name; elsewhere 0.0.0.0 (APP_BIND opened to the
  # LAN) is reached on loopback.
  local host=127.0.0.1
  [ -f /.dockerenv ] && host=host.docker.internal
  address="$(compose "$pr" port app 8000 | sed "s/^0\.0\.0\.0:/$host:/;s/^127\.0\.0\.1:/$host:/")"
  for _ in $(seq 1 60); do
    if curl -fs -o /dev/null "http://$address/"; then
      # A rebuild moves the image tags and leaves the previous build dangling.
      docker image prune -f >/dev/null
      echo "preview $pr en ligne sur le port $(port_for "$pr") (commit ${sha:0:7})"
      return 0
    fi
    sleep 2
  done
  compose "$pr" logs --tail 50 >&2 || true
  echo "preview.sh: la preview $pr ne répond pas sur le port $(port_for "$pr") après 120 s" >&2
  exit 1
}

cmd_down() {
  require_pr "${1:-}"
  local pr="$1" src
  src="$(worktree_for "$pr")"
  compose "$pr" down -v --remove-orphans --rmi all >/dev/null 2>&1 || true
  if [ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" = "true" ]; then
    db_psql dropdb -U raton --if-exists --force "raton_pr_$pr"
  fi
  if [ -d "$src" ]; then git worktree remove --force "$src"; fi
  git worktree prune
  git update-ref -d "refs/previews/pr-$pr" 2>/dev/null || true
  echo "preview $pr supprimée"
}

cmd_list() {
  local pr sha state db
  # A preview built before the DB label has none: "-" keeps the columns aligned.
  docker ps -a --filter label=raton.preview.pr \
    --format '{{.Label "raton.preview.pr"}}|{{.Label "raton.preview.sha"}}|{{.State}}|{{.Label "raton.preview.db"}}' |
    while IFS='|' read -r pr sha state db; do
      echo "$pr $(port_for "$pr") ${sha:--} $state ${db:--}"
    done
}

# Catches what a forgotten `down` left behind. A PR whose state cannot be read is kept:
# better a stale preview than one removed by a GitHub API hiccup.
cmd_sweep() {
  local pr state
  for pr in $(cmd_list | cut -d' ' -f1); do
    state="$(gh pr view "$pr" --json state --jq .state 2>/dev/null || true)"
    if [ -n "$state" ] && [ "$state" != "OPEN" ]; then cmd_down "$pr"; fi
  done
}

# A preview on the real DB runs its PR's code against it: once a deploy migrates that DB, the
# old code writes rows the new schema refuses (a column became NOT NULL...). Its PR must merge
# main to get a preview again; `up` then picks a copy or the real DB as usual.
cmd_retire_stale() {
  local target pr head
  for pr in $(cmd_list | awk '$5 == "shared" { print $1 }'); do
    target="${target:-$(python3 "$REPO/scripts/preview_db.py" head "$REPO/alembic/versions")}"
    head="$(python3 "$REPO/scripts/preview_db.py" head "$(worktree_for "$pr")/alembic/versions" 2>/dev/null || true)"
    if [ "$head" != "$target" ]; then
      echo "preview $pr : branchée sur la DB réelle, que ce déploiement migre en $target : retirée"
      cmd_down "$pr"
    fi
  done
}

case "${1:-}" in
  up) cmd_up "${2:-}" ;;
  down) cmd_down "${2:-}" ;;
  list) cmd_list ;;
  sweep) cmd_sweep ;;
  retire-stale) cmd_retire_stale ;;
  *) echo "usage: preview.sh up <pr> | down <pr> | list | sweep | retire-stale" >&2; exit 2 ;;
esac
