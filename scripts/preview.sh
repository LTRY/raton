#!/usr/bin/env bash
# The PR previews: one throwaway Raton (back + front, demo data) per pull request, on port
# 9000 + its number. Driven by hand or by the previews page (scripts/previews.py).
#
#   preview.sh up <pr>     build the PR's current head and (re)start its preview
#   preview.sh down <pr>   remove the PR's preview: containers, images, worktree
#   preview.sh list        one line per preview: <pr> <port> <commit> <container state>
#   preview.sh sweep       remove the previews of the PRs that are no longer open
#
# Each preview is its own compose project (raton-pr-<pr>, docker-compose.preview.yml), built
# from a git worktree of the PR's head in .local/previews/pr-<pr>. Same-repository PRs only:
# the host builds and runs the PR's code, so a fork's PR never gets one.
# Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
set -euo pipefail

BASE_PORT=9000

cd "$(dirname "$0")/.."
REPO="$PWD"

port_for() { echo $((BASE_PORT + $1)); }
worktree_for() { echo "$REPO/.local/previews/pr-$1"; }

require_pr() {
  [[ "${1:-}" =~ ^[0-9]+$ ]] || { echo "preview.sh: numéro de PR attendu, reçu '${1:-}'" >&2; exit 2; }
}

# Always with the preview file: a bare `docker compose` here would load the real stack's file.
compose() {
  local pr="$1"; shift
  PREVIEW_PR="$pr" PREVIEW_PORT="$(port_for "$pr")" PREVIEW_SRC="$(worktree_for "$pr")" \
    docker compose -p "raton-pr-$pr" -f "$REPO/docker-compose.preview.yml" "$@"
}

cmd_up() {
  require_pr "${1:-}"
  local pr="$1" info state cross sha src address
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
  echo "preview $pr : commit ${sha:0:7}, construction..."

  export PREVIEW_SHA="$sha"
  if ! compose "$pr" up -d --build --force-recreate --remove-orphans; then
    echo "preview.sh: la construction de la preview $pr a échoué" >&2; exit 1
  fi
  # Inside the host, 0.0.0.0 (APP_BIND opened to the LAN) is reached on loopback.
  address="$(compose "$pr" port app 8000 | sed 's/^0\.0\.0\.0:/127.0.0.1:/')"
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
  if [ -d "$src" ]; then git worktree remove --force "$src"; fi
  git worktree prune
  git update-ref -d "refs/previews/pr-$pr" 2>/dev/null || true
  echo "preview $pr supprimée"
}

cmd_list() {
  local pr sha state
  docker ps -a --filter label=raton.preview.pr \
    --format '{{.Label "raton.preview.pr"}} {{.Label "raton.preview.sha"}} {{.State}}' |
    while read -r pr sha state; do
      echo "$pr $(port_for "$pr") ${sha:--} $state"
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

case "${1:-}" in
  up) cmd_up "${2:-}" ;;
  down) cmd_down "${2:-}" ;;
  list) cmd_list ;;
  sweep) cmd_sweep ;;
  *) echo "usage: preview.sh up <pr> | down <pr> | list | sweep" >&2; exit 2 ;;
esac
