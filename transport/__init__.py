"""Transport adapters for jobContextMCP.

Submodules:
    http/   FastAPI + SSE adapter for browser / iPad / Open WebUI clients.

The existing stdio MCP server lives at `server.py` in the repo root and is
unchanged by these adapters. Both transports import the same `tools/` and
`services/` packages, so business logic is shared.
"""
