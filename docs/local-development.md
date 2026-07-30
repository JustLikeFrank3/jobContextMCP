# Local Development Workflow

If you're adding tools, modifying services, or debugging — run from a local venv. Docker is the right call for sharing, releases, and CI; it's the wrong call for iteration. A `docker compose build` after every code change is ~30s of friction per loop; a local-venv restart is ~0.5s.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

> `requirements.txt` pins `mcp[cli]<2` — mcp 2.0.0 removed `mcp.server.fastmcp`. Don't `pip install -U` past the pin.

## Two ways to run the server

**MCP stdio** (what MCP clients spawn):

```bash
.venv/bin/python server.py
```

**HTTP transport** (REST API + dashboard + MCP Streamable HTTP at `/mcp`):

```bash
PORT=8000 .venv/bin/python -m transport.http.main
```

See [http-api.md](http-api.md) for the endpoint surface and [api-reference.md](api-reference.md) for full schemas.

## Connecting VS Code to a local checkout

The committed [.vscode/mcp.json](../.vscode/mcp.json) points at the hosted Streamable HTTP endpoint. For local stdio development, replace the server entry with:

```jsonc
"jobContextMCP": {
  "type": "stdio",
  "command": "${workspaceFolder}/.venv/bin/python3",
  "args": ["server.py"],
  "cwd": "${workspaceFolder}"
}
```

Then **Command Palette → MCP: List Servers → restart jobContextMCP**. You should see `Discovered 11 tools` within ~0.5s.

> ⚠️ **Do not add the server via the VS Code UI** (plug icon → "Add MCP Server"). It writes a broken entry to the global user `mcp.json` (`python` instead of `python3`, no `cwd`) that silently conflicts with the workspace config. If tools behave flakily, remove any duplicate `jobContextMCP` entry from that global file.

## What's live vs. baked-in

`docker-compose.yml` bind-mounts `./data` and `./config.json`, so **data changes (JSON state, RAG index, embeddings) are live in both modes**. But Python source is `COPY .`'d into the image at build time, so **code changes in Docker mode require a rebuild**.

| Mode | Code changes | Data changes | Restart cycle |
|---|---|---|---|
| local venv | Live on MCP restart | Live (same files) | Restart MCP server in VS Code (~0.5s) |
| docker | Requires image rebuild | Live (bind-mounted) | `docker compose build` + restart (~30s+) |

## Validate the Docker image before a release

```bash
docker compose build jobcontextmcp
```

Verify mode parity — both should print the same count:

```bash
.venv/bin/python3 -c "import server; print('local:', len(server.mcp._tool_manager.list_tools()))"
docker compose run --rm jobcontextmcp python3 -c "import server; print('docker:', len(server.mcp._tool_manager.list_tools()))"
```

If the counts diverge, the likely cause is uncommitted code changes (local sees them; the Docker image doesn't until rebuild).

For pre-deploy testing against real Kubernetes manifests, there's also a disposable local k3d cluster — see [local-cluster.md](local-cluster.md).

## Enabling SQLite locally

By default the local server reads and writes JSON files under `data/`. The SQLite layer (the default in cloud and desktop deployments) is available locally too — reads come from `jobcontextmcp.db`, writes go to both stores so you can roll back to JSON at any time.

```bash
.venv/bin/python scripts/migrate_to_sqlite.py   # one-time bootstrap from existing JSON
```

> The migration script reads from and writes to `data_dev/` (gitignored), and it deletes and recreates the target `.db` on every run — copy your `data/` files there first. It also owns the canonical schema DDL.

```dotenv
USE_SQLITE=1     # reads from SQLite, dual-writes both stores
# SQLITE_ONLY=1  # skips JSON writes for mapped tables (the cloud/desktop default)
```

## Running the tests

```bash
.venv/bin/python -m pytest                       # full suite
.venv/bin/python -m pytest tests/test_evals.py   # one module
.venv/bin/python scripts/ci_smoke_gate.py        # the Layer 1 eval smoke gate CI runs
```

### Test-suite gotchas

- `tests/conftest.py` has an autouse fixture that stubs `lib.config.get_llm_client` to `(None, None)` — code needing real key-resolution truth in tests must not call it.
- CI's test env sets `LLM_PROVIDER=foundry` — provider-sensitive tests must `monkeypatch.delenv("LLM_PROVIDER")`. Run suites both ways when touching provider logic.
- The `isolated_server` fixture is the canonical isolation mechanism; static module-level path constants are computed at import time — repoint them, don't re-derive.
- Sonar quality gate requires ≥80% coverage on new code.
