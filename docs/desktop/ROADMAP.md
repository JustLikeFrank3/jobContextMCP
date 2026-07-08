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
| 2 | PDF engine spike (WeasyPrint freeze vs Typst vs hybrid) | ✅ **keep WeasyPrint** — verified frozen on macOS (local) + Windows & Linux (CI selftest) |
| 3 | PyInstaller onedir freeze of backend (`desktop_main.py`) | ✅ spec + hooks + selftest; windows-x64 & linux-x64 green in CI, macOS fix landed (custom weasyprint hook) |
| 4 | Tauri 2 shell + sidecar lifecycle | ✅ compiled & verified live on macOS (dashboard in webview); anti-orphan watchdog covers SIGTERM/SIGKILL; tray mode deferred |
| 5 | MCP client one-click connect (`--mcp-stdio` flag already shipped) | ✅ endpoints + Settings UI ("AI clients (MCP)" section, desktop-only); live-verified detection of Claude Desktop / VS Code / Cursor |
| 5.5 | Embedded chat panel (agent loop + tool calling in the SPA) | ✅ agent loop + SSE + persistence, chat UI w/ tool chips + model indicator, Anthropic/OpenAI/Ollama BYOK with in-app Settings key entry — all live-verified; deferred polish: markdown rendering, token streaming |
| 6 | Installers (dmg / NSIS+msi / AppImage+deb) | ✅ all four platforms green in CI (2026-07-06): arm64+Intel dmg, NSIS exe+msi, AppImage+deb — unsigned pending Phase 7 |
| 7 | Signing & notarization | ✅ (2026-07-06) Windows Authenticode via Azure Trusted Signing (individual validation; org later). macOS Developer ID + notarization green: sign the **final** .app with rcodesign two-pass — Tauri's resource copy dereferences symlinks into duplicate Python Mach-Os that pre-bundle signing can never cover; notarytool crashes on GH runners → rcodesign notary-submit + staple |
| 8 | Auto-update + GitHub Actions release matrix | ◐ release pipeline done & validated: reusable desktop-build.yml shared by Desktop CI (branch pushes) and Desktop Release (`desktop-v*` tags → version-stamped pre-release with installers; namespace disjoint from cloud `v*`/AKS). updater plugin shipped (launch-time check against the rolling desktop-latest manifest, native dialog, update & restart) — first self-update exercised beta.5 → beta.6 |
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

## Phase 5.5 scope — embedded chat (queued after Phase 8, ~5–7 d)

Chat panel inside the desktop app, complementing (not replacing) the
"bring your own Claude" MCP story. Key accelerators already in the repo:
`server.mcp.list_tools()` returns all 85 tools with JSON schemas in-process
(function-calling conversion is mechanical), `services/events.py` already
does SSE, and `get_llm_client()` abstracts OpenAI/Azure/Ollama — Anthropic
BYOK rides the same factory via their OpenAI-compatible endpoint.

- Agent loop (1–2 d): model → tool calls → execute → repeat, streamed over
  SSE; loop caps, tool-error recovery, token budgets are the real work.
- Tool curation (0.5 d): ~15–20 chat-allowlisted tools (queue, assess,
  generate, status, interviews), not all 85 in one context window.
- Persistence (0.5 d): chat_sessions + chat_messages tables via the
  existing migration pattern.
- Chat UI (2–3 d): streaming markdown, tool-activity indicators, stop
  button — the single biggest item; "good," not Claude.ai-grade.
- Settings + key handling (0.5 d): reuse Fernet-encrypted BYOK storage.
- Tests (1 d): mocked-client loop tests via the `live_llm` marker pattern.

Desktop-gated initially (single user, localhost — no tenancy questions).

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
- **PDF engine**: **keep WeasyPrint** (spike result, 2026-07-06). The macOS
  arm64 PyInstaller freeze bundles Pango/Cairo/HarfBuzz/fontconfig from
  Homebrew automatically (pyinstaller-hooks-contrib), rewrites all load paths
  to `@rpath` (portable, no Homebrew references), and `--selftest` renders a
  real PDF from the frozen bundle. Bundle is ~106 MB onedir. Windows (MSYS2
  GTK DLLs) still needs CI validation; Typst remains the documented escape
  hatch if that fights back.

## Phase 2/3 spike results (2026-07-06, macOS arm64)

- `packaging/pyinstaller/jobcontext-backend.spec` — onedir build, ~21 s.
  Only two hidden imports needed: `tiktoken_ext` + `tiktoken_ext.openai_public`.
  langgraph, cryptography, numpy, uvicorn, mcp all froze with stock hooks.
- **macOS dylib saga** (the roadmap's predicted `install_name_tool` pain,
  resolved 2026-07-06): a truly self-contained WeasyPrint stack needs all
  three of: (1) a runtime hook so `find_library` searches the bundle
  (Homebrew-patched CPython hides this failure on dev machines), (2)
  collecting the Homebrew libs realpath-deduped into `weasyprint_libs/` so
  PyInstaller can't dedup them against Pillow's vendored harfbuzz, and (3)
  spec post-processing that rebinds intra-dir deps to `@loader_path`
  siblings + ad-hoc re-signs — otherwise Pango loads Pillow's harfbuzz while
  WeasyPrint dlopens Homebrew's, and an `hb_face_t` crossing two harfbuzz
  builds dies with SIGBUS. Verified with `DYLD_PRINT_LIBRARIES=1`: zero
  `/opt/homebrew` loads.
- `desktop_main.py --selftest` diagnostics (config / sqlite / tools /
  templates / pdf) all PASS from the frozen binary; intended as the CI smoke
  test on every platform build.
- Frozen HTTP server verified end to end: boots, prints port, serves
  `/healthz` and the React SPA at `/app`, `/desktop/shutdown` exits cleanly.

## Top risks (tracking)

1. WeasyPrint native libs in the Windows freeze — spike first.
2. PyInstaller hidden imports (tiktoken data files, langgraph, cryptography).
3. Orphaned backend / SQLite lock — mitigated (shutdown endpoint); add
   single-instance lock in the Tauri shell.
4. Notarization: sign every Mach-O in the onedir bundle, not just the app.
5. Cert lead times — enroll Apple Developer Program (as jobContext LLC) and
   Azure Trusted Signing in parallel with Phases 2–3.
