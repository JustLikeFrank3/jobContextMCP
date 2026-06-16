#!/usr/bin/env bash
# start_server.sh — Start jobContextMCP on Tailscale LAN
# Usage: ./scripts/start_server.sh [port]
#
# Binds to 0.0.0.0 via ENABLE_REMOTE=true, making the server reachable
# on both Tailscale and the local LAN. Set API_KEY in your environment
# or .env to require bearer-token auth.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
_CLI_PORT="${1:-}"  # capture CLI arg before .env load

cd "$REPO_DIR"

# Load .env if present (API_KEY, CORS_ORIGINS, etc.)
if [[ -f .env ]]; then
    set -a
    # shellcheck source=/dev/null
    source .env
    set +a
fi

# CLI arg always wins over .env PORT; fall back to .env PORT, then 8000
PORT="${_CLI_PORT:-${PORT:-8000}}"
TS_IP="$(tailscale ip --4 2>/dev/null)" || { echo "WARNING: Tailscale not running — LAN only"; TS_IP="(unavailable)"; }

echo "Starting jobContextMCP..."
echo "  Tailscale : http://${TS_IP}:${PORT}"
echo "  Local     : http://127.0.0.1:${PORT}"
echo ""

# Kill anything already on the port
lsof -ti tcp:"${PORT}" | xargs -r kill 2>/dev/null || true
sleep 0.5

exec env ENABLE_REMOTE=true PORT="${PORT}" \
    .venv.nosync/bin/python -m transport.http.main
