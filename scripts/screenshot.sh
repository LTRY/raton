#!/usr/bin/env bash
# Screenshot one page of the app at desktop and phone width, and check it does not scroll sideways.
#
# Usage: scripts/screenshot.sh [path] [out-dir]     (default: / and ./.local/screenshots)
#
# Runs the app against a throwaway sqlite database seeded with the demo data, in a scratch
# directory — never the user's real data — then stops it. Needs Node (Playwright is installed
# in the scratch directory, Chromium is cached by Playwright after the first run).
set -euo pipefail

page_path="${1:-/}"
out_dir="${2:-.local/screenshots}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"
port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
server_pid=""
back_pid=""

cleanup() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; fi
  if [ -n "$back_pid" ]; then kill "$back_pid" 2>/dev/null || true; fi
  rm -rf "$scratch"
}
trap cleanup EXIT

export DATABASE_URL="sqlite+pysqlite:///$scratch/raton.db"
export MEDIA_ROOT="$scratch/media"
export APP_AUTO_CREATE_TABLES=true
mkdir -p "$MEDIA_ROOT"

cd "$repo"
uv run --python 3.14 python -m scripts.demo_seed
# The back (API) on its own port, the front (the pages, what is shot) on `$port`.
back_port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
uv run --python 3.14 uvicorn back.main:app --host 127.0.0.1 --port "$back_port" --log-level warning &
back_pid=$!
for _ in $(seq 1 120); do
  curl -fs "http://127.0.0.1:$back_port/api/stats" -o /dev/null && break
  sleep 0.5
done
RATON_API_URL="http://127.0.0.1:$back_port" uv run --python 3.14 uvicorn front.main:app --host 127.0.0.1 --port "$port" --log-level warning &
server_pid=$!
for _ in $(seq 1 120); do
  curl -fs "http://127.0.0.1:$port/" -o /dev/null && break
  sleep 0.5
done

(cd "$scratch" && npm init -y >/dev/null && npm install --silent playwright && npx playwright install chromium >/dev/null)

cat >"$scratch/shoot.js" <<'JS'
const { chromium } = require("playwright");
const [url, outDir] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  for (const [name, width, height] of [["desktop", 1280, 700], ["phone", 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.goto(url, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: name === "phone" });
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    const verdict = scrollWidth === clientWidth ? "ok" : "OVERFLOW";
    console.log(`${name} (${width}px): scrollWidth=${scrollWidth} clientWidth=${clientWidth} ${verdict}`);
  }
  await browser.close();
})();
JS

NODE_PATH="$scratch/node_modules" node "$scratch/shoot.js" "http://127.0.0.1:$port$page_path" "$out_dir"
echo "Screenshots in $out_dir (desktop.png, phone.png)"
