#!/usr/bin/env bash
# ── run_mcp.sh ────────────────────────────────────────────────────────────────
# Dispatches jobContextMCP in Docker or local-venv mode based on MCP_MODE.
#
# Set in .env (or export before launching VS Code / on the CLI):
#   MCP_MODE=docker   → docker compose run --rm -i jobcontextmcp  (default)
#   MCP_MODE=local    → <auto-detected venv>/bin/python3 server.py
#
# Precedence: CLI/inherited env vars > .env file > hardcoded default.
# So you can test ad-hoc without editing .env:
#   MCP_MODE=local ./scripts/run_mcp.sh
#
# VS Code mcp.json always points here — switch modes by changing one line in .env.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Save caller-provided overrides BEFORE sourcing .env so CLI/inherited env wins.
# (set -a + source unconditionally overwrites, which would let .env clobber the caller.)
_OVERRIDE_MCP_MODE="${MCP_MODE-}"

# Load .env if present (silently — do not abort if missing)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

# Restore CLI override if it was set; else use .env value; else default to docker
MCP_MODE="${_OVERRIDE_MCP_MODE:-${MCP_MODE:-docker}}"
unset _OVERRIDE_MCP_MODE

# Resolve venv: prefer .venv, fall back to .venv.nosync (iCloud's "don't sync" suffix).
resolve_venv_python() {
    for candidate in "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/.venv.nosync/bin/python3"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

case "$MCP_MODE" in
    local)
        if ! VENV_PY="$(resolve_venv_python)"; then
            echo "run_mcp.sh: no venv found at $REPO_ROOT/.venv or $REPO_ROOT/.venv.nosync" >&2
            echo "  create one with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
            exit 1
        fi
        exec "$VENV_PY" "$REPO_ROOT/server.py"
        ;;
    docker)
        exec docker compose -f "$REPO_ROOT/docker-compose.yml" run --rm -i jobcontextmcp
        ;;
    *)
        echo "run_mcp.sh: unknown MCP_MODE='$MCP_MODE'. Valid values: docker, local" >&2
        exit 1
        ;;
esac
