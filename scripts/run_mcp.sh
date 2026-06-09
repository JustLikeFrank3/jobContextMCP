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
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present (silently — do not abort if missing)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

MCP_MODE="${MCP_MODE:-docker}"

case "$MCP_MODE" in
    local)
        exec "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/server.py"
        ;;
    docker)
        exec docker compose -f "$REPO_ROOT/docker-compose.yml" run --rm -i jobcontextmcp
        ;;
    *)
        echo "run_mcp.sh: unknown MCP_MODE='$MCP_MODE'. Valid values: docker, local" >&2
        exit 1
        ;;
esac
