#!/usr/bin/env bash
# Removes what `make install`, `make up` and `make demo` put on this machine.
#
# Default: stops the stack and removes its containers, the local image, .venv
# and the cached Tailwind binary. Your data stays: the PostgreSQL volume, the
# media library, the logs, the demo database and .env.
#
#   --purge        also delete the PostgreSQL volume, the logs and the demo database
#   --purge-media  also delete the media library (MEDIA_HOST_ROOT)
#   -y, --yes      do not ask for confirmation
set -euo pipefail

cd "$(dirname "$0")/.."

# Host folder holding the media library, as `make up` sees it: the environment,
# then .env, then the default of docker-compose.yml.
media_host_root() {
  local value="${MEDIA_HOST_ROOT:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(sed -n 's/^MEDIA_HOST_ROOT=//p' .env | tail -n 1 | tr -d "\"'")"
  fi
  value="${value:-./.local/media/YouTube}"
  [ -d "$value" ] || return 1
  (cd "$value" && pwd)
}

purge=0 purge_media=0 yes=0
for arg in "$@"; do
  case "$arg" in
    --purge) purge=1 ;;
    --purge-media) purge_media=1 ;;
    -y|--yes) yes=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "uninstall.sh: unknown option $arg" >&2; exit 2 ;;
  esac
done

media_root="$(media_host_root 2>/dev/null || true)"
log_dir="${LOG_HOST_DIR:-./.local/logs}"

echo "This will remove:"
echo "  - the docker compose stack (containers, network) and the raton:local and raton-api:local images"
echo "  - .venv and .local/bin"
[ "$purge" = 1 ] && echo "  - the PostgreSQL volume, $log_dir and .local/raton.db (ALL DATABASE DATA)"
[ "$purge_media" = 1 ] && echo "  - the media library: ${media_root:-<not found>} (ALL DOWNLOADED FILES)"
kept=(.env)
[ "$purge" = 0 ] && kept+=("the PostgreSQL volume" "logs")
[ "$purge_media" = 0 ] && kept+=("the media library")
echo "Kept: $(IFS=,; echo "${kept[*]}")"

if [ "$yes" = 0 ]; then
  read -r -p "Continue? [y/N] " answer
  case "$answer" in y|Y|yes) ;; *) echo "Aborted."; exit 1 ;; esac
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  down=(docker compose down --remove-orphans --rmi local)
  [ "$purge" = 1 ] && down+=(--volumes)
  "${down[@]}" || echo "uninstall.sh: docker compose down failed, continuing" >&2
else
  echo "uninstall.sh: docker not available, skipping containers and image" >&2
fi

rm -rf .venv .local/bin

if [ "$purge" = 1 ]; then
  rm -rf "$log_dir" .local/raton.db
fi

if [ "$purge_media" = 1 ]; then
  if [ -n "$media_root" ] && [ "$media_root" != "/" ] && [ "$media_root" != "$HOME" ]; then
    rm -rf "$media_root"
  else
    echo "uninstall.sh: media folder not found or unsafe, not deleting it" >&2
  fi
fi

# Remove .local only when nothing of yours is left in it.
rmdir .local/media .local 2>/dev/null || true

echo "Raton is uninstalled. To finish, delete this folder."
