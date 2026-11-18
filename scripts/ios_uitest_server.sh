#!/usr/bin/env bash
# The servers of the iOS UI tests (ios/RatonUITests): the back on port 8001 (scripts/ios_uitest_server.py,
# demo data, no network) and the front on port 8000, on a throwaway sqlite database. Returns once both
# answer and leaves them running in the background (`pkill -f ios_uitest_server` and `pkill -f front.main`
# stop them); with `--foreground` it stays attached until Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")/.."

work="${RATON_UITEST_DIR:-$PWD/.local/ios-uitest}"
rm -rf "$work"
mkdir -p "$work/media"
export DATABASE_URL="sqlite+pysqlite:///$work/raton.db" MEDIA_ROOT="$work/media" APP_AUTO_CREATE_TABLES=true \
  APP_SCHEDULER_ENABLED=false

uv run --python 3.14 python -m scripts.demo_seed
# Their output goes to files: a caller that pipes this script would otherwise wait for the servers to end.
uv run --python 3.14 python -m scripts.ios_uitest_server >"$work/back.log" 2>&1 &
back_pid=$!
# The front is started once the back answers, so that it does not log failed relays while it boots.
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:8001/api/channels" >/dev/null 2>&1 && break; sleep 1; done
RATON_API_URL=http://127.0.0.1:8001 uv run --python 3.14 uvicorn front.main:app --host 127.0.0.1 --port 8000 \
  --log-level warning >"$work/front.log" 2>&1 &
front_pid=$!

for _ in $(seq 1 90); do
  if curl -fs "http://127.0.0.1:8000/api/channels" >/dev/null 2>&1; then
    echo "iOS UI test servers ready (back $back_pid, front $front_pid)"
    [ "${1:-}" = "--foreground" ] && { trap 'kill $back_pid $front_pid 2>/dev/null' EXIT; wait; }
    exit 0
  fi
  sleep 1
done
echo "the servers did not start" >&2
kill "$back_pid" "$front_pid" 2>/dev/null || true
exit 1
