# jobContext Desktop — Roadmap & Status

Goal: a double-clickable jobContext Desktop app — `.dmg` (macOS), signed
`.exe`/`.msi` (Windows), `.AppImage` + `.deb` (Linux) — bundling the Python
MCP server, the React dashboard, and local SQLite storage with zero terminal
setup. The AKS cloud product is unchanged; this is a second distribution
channel from the same codebase.

**Stack decision:** Tauri 2 shell + PyInstaller-frozen backend sidecar
(Option A). The PyInstaller work is validated first standalone, so a
pywebview spike remains a cheap fallback demo if ever needed.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Product decisions (local-first profile, app-data dirs, BYOK LLM, tool scoping) | ✅ decided; profile shipped |
| 1 | Backend decoupling: `DEPLOY_MODE=desktop`, platformdirs, bootstrap, healthz, port 0, shutdown | ✅ done |
| 2 | PDF engine spike (WeasyPrint freeze vs Typst vs hybrid) | ⬜ next — biggest risk, do early |
| 3 | PyInstaller onedir freeze of backend (`desktop_main.py`) | ⬜ |
| 4 | Tauri 2 shell + sidecar lifecycle | ⬜ |
| 5 | MCP client one-click connect (`--mcp-stdio` flag already shipped) | ◐ flag done; Settings buttons pending |
| 6 | Installers (dmg / NSIS+msi / AppImage+deb) | ⬜ |
| 7 | Signing & notarization — **start Apple Dev Program + Azure Trusted Signing paperwork now** | ⬜ lead-time bound |
| 8 | Auto-update + GitHub Actions release matrix | ⬜ |
| 9 | QA on clean VMs, beta, launch | ⬜ |

## What Phase 0/1 shipped

- `lib/app_dirs.py` — `is_desktop_mode()`, `desktop_data_dir()`
  (platformdirs; `~/Library/Application Support/jobContext`,
  `%APPDATA%\jobContext`, `~/.local/share/jobContext`; `JOBCONTEXT_DATA_DIR`
  override), and `resource_root()` (sys._MEIPASS-aware) used for the SPA dist.
- `lib/config.py` — `JOBCONTEXT_CONFIG` env var points the config loader at
  the app-data dir (installed apps are read-only next to the executable).
- `transport/http/config.py` — `DEPLOY_MODE=desktop` profile: loopback-only
  bind, `ENABLE_REMOTE` ignored.
- `transport/http/desktop.py` + `create_app()` — `POST /desktop/shutdown`
  (desktop mode only) so the shell can stop the backend without orphaning it.
- `transport/http/routes/health.py` — `/healthz` alias for shell polling.
- `desktop_main.py` — PyInstaller entrypoint: applies desktop env
  (`USE_SQLITE=1`, `SQLITE_ONLY=1`, Entra/remote stripped), first-run
  bootstrap reusing `provision_user_data`, binds `127.0.0.1:0` and prints
  `JOBCONTEXT_PORT=<port>` (socket handed to uvicorn — no rebind race),
  `--mcp-stdio` runs the stdio MCP transport against the same data dir.
- `tests/test_desktop_mode.py` — 17 tests; full suite 1,248 green.

Smoke-tested end to end: boot → port discovery → `/healthz` →
`/desktop/shutdown` → clean exit; app-data dir provisioned (config.json, db,
workspace tree, personas).

## Shell contract (for Phase 4)

1. Spawn sidecar: `jobcontext-backend [--data-dir <dir>]`.
2. Read stdout for the line `JOBCONTEXT_PORT=<port>` (format is stable).
3. Poll `GET /healthz` until 200, then open webview at
   `http://127.0.0.1:<port>/app`.
4. On window close: `POST /desktop/shutdown` (or SIGTERM); the backend exits
   gracefully.

## Key decisions log

- **Desktop = single-user, local-first.** No Entra, no Blob, no multi-tenant;
  `_apply_desktop_env` strips those vars. Auth disabled ⇒ local admin (same
  as the existing no-API_KEY local-dev path).
- **App data**: everything under the per-OS app-data dir; `data_folder` IS
  the app dir, workspace at `<appdir>/workspace`, DB at
  `<appdir>/db/jobcontextmcp.db` — same layout as an AKS tenant partition,
  so all existing path logic holds.
- **LLM**: BYOK OpenAI key in config.json + existing Ollama support
  (`llm_provider: "ollama"`); everything degrades gracefully with no key
  (`get_llm_client` already returns `(None, "")`).
- **PDF engine**: undecided — Phase 2 spike (WeasyPrint freeze on Windows is
  the risk; Typst or `PDF_ENGINE` hybrid is the escape hatch).

## Top risks (tracking)

1. WeasyPrint native libs in the Windows freeze — spike first.
2. PyInstaller hidden imports (tiktoken data files, langgraph, cryptography).
3. Orphaned backend / SQLite lock — mitigated (shutdown endpoint); add
   single-instance lock in the Tauri shell.
4. Notarization: sign every Mach-O in the onedir bundle, not just the app.
5. Cert lead times — enroll Apple Developer Program (as jobContext LLC) and
   Azure Trusted Signing in parallel with Phases 2–3.
