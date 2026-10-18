#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): formats and auto-fixes the Python
# file Claude just wrote, so `make ci` never fails on style alone. Exits 2 when
# ruff still reports something it cannot fix; that message goes back to Claude.

main() {
  local file
  file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null)
  case "$file" in
    *.py) ;;
    *) return 0 ;;
  esac
  [ -f "$file" ] || return 0

  cd "$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
  uv run --quiet --python 3.14 --extra dev ruff format --quiet "$file" >/dev/null 2>&1 || return 0
  local out
  if ! out=$(uv run --quiet --python 3.14 --extra dev ruff check --fix --output-format concise "$file" 2>&1); then
    echo "$out" >&2
    return 2
  fi
}

main
exit $?
