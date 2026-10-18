#!/usr/bin/env bash
# Compiles app/static/css/tailwind.input.css into app/static/css/app.css using
# the Tailwind standalone CLI (no Node/npm required). The binary is cached in
# .local/bin (gitignored) and downloaded on first use, matching the pattern
# already used by .local/media and .local/*.db for machine-local state.
set -euo pipefail

cd "$(dirname "$0")/.."

TAILWIND_VERSION="v4.3.3"
BIN_DIR=".local/bin"
BIN_PATH="$BIN_DIR/tailwindcss"

if [ ! -x "$BIN_PATH" ]; then
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os-$arch" in
    Darwin-arm64) asset="tailwindcss-macos-arm64" ;;
    Darwin-x86_64) asset="tailwindcss-macos-x64" ;;
    Linux-x86_64) asset="tailwindcss-linux-x64" ;;
    Linux-aarch64|Linux-arm64) asset="tailwindcss-linux-arm64" ;;
    *) echo "build_css.sh: unsupported platform $os-$arch" >&2; exit 1 ;;
  esac
  mkdir -p "$BIN_DIR"
  url="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}"
  echo "build_css.sh: downloading tailwindcss ${TAILWIND_VERSION} (${asset})" >&2
  curl -sSL -o "$BIN_PATH" "$url"
  chmod +x "$BIN_PATH"
fi

"$BIN_PATH" -i app/static/css/tailwind.input.css -o app/static/css/app.css --minify "$@"
