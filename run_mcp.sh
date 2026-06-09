#!/usr/bin/env bash
# ── run_mcp.sh ────────────────────────────────────────────────────────────────
# Dispatches jobContextMCP in Docker or local-venv mode based on MCP_MODE.
#
# Set in .env (or export before launching VS Code):
#   MCP_MODE=docker   → docker compose run --rm -i jobcontextmcp  (default)
#   MCP_MODE=local    → .venv/bin/python3 server.py
#
# VS Code mcp.json always points here — switch modes by changing one line in .env.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if present (silently — do not abort if missing)
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

MCP_MODE="${MCP_MODE:-docker}"

case "$MCP_MODE" in
    local)
        exec "$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/server.py"
        ;;
    docker)
        exec docker compose -f "$SCRIPT_DIR/docker-compose.yml" run --rm -i jobcontextmcp
        ;;
    *)
        echo "run_mcp.sh: unknown MCP_MODE='$MCP_MODE'. Valid values: docker, local" >&2
        exit 1
        ;;
esac
