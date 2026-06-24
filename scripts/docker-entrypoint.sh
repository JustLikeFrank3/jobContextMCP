#!/bin/sh
# docker-entrypoint.sh — Select server mode at container start.
#
# START_MODE=http  → FastAPI HTTP transport (dashboard + REST API)
#                    Used for AKS / any network-accessible deployment.
#                    Reads HOST / PORT / ENABLE_REMOTE / API_KEY from env.
#
# START_MODE=mcp   → MCP server (stdio / SSE / streamable-http)
# (default)           Used for Claude Desktop and direct MCP client connections.
#                    Reads MCP_TRANSPORT / MCP_HOST / MCP_PORT from env.
#
# Any extra arguments are forwarded to the selected process.

set -e

case "${START_MODE:-mcp}" in
    http)
        exec python -m transport.http.main "$@"
        ;;
    mcp)
        exec python server.py "$@"
        ;;
    *)
        echo "ERROR: Unknown START_MODE '${START_MODE}'. Use 'http' or 'mcp'." >&2
        exit 1
        ;;
esac
