# jobContext Desktop (Tauri 2 shell)

Native desktop shell that spawns the PyInstaller-frozen backend as a managed
sidecar and renders the React dashboard in the OS webview. See
[docs/desktop/ROADMAP.md](../docs/desktop/ROADMAP.md) for the full plan and
the shell↔backend contract.

> **Status: scaffolded, not yet compiled.** The Rust toolchain is not
> installed on the dev machine yet; expect to iterate on first
> `npm run dev`. Everything backend-side (sidecar binary, port discovery,
> /healthz, /desktop/shutdown) is built and verified.

## Prerequisites

- Rust toolchain: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Node 20+ (already required for the SPA)
- Platform webview deps: none on macOS/Windows; on Linux
  `libwebkit2gtk-4.1-dev` + `libappindicator3-dev` etc. (see Tauri 2 docs)

## Build & run (dev)

```bash
# 1. Build the SPA (bundled into the backend, served at /app)
cd frontend && npm ci && npm run build && cd ..

# 2. Freeze the backend sidecar (repo root)
pip install -r requirements-dev.txt
pyinstaller packaging/pyinstaller/jobcontext-backend.spec --noconfirm
dist/jobcontext-backend/jobcontext-backend --selftest   # must print SELFTEST PASS

# 3. Run the shell — in dev it finds the sidecar at ../dist automatically
cd desktop && npm install
npm run icon    # once: generates src-tauri/icons/ from icon-source.png
npm run dev
```

## Bundling installers

`tauri.conf.json` bundles `src-tauri/binaries/jobcontext-backend/` as a
resource directory (a onedir sidecar can't use Tauri's `externalBin`, which
expects single files). Before `npm run build`, copy the frozen backend in:

```bash
mkdir -p desktop/src-tauri/binaries
cp -R dist/jobcontext-backend desktop/src-tauri/binaries/
cd desktop && npm run build
```

Targets configured: `dmg` (macOS), `nsis` per-user + `msi` (Windows),
`appimage` + `deb` (Linux). CI wiring, signing, and the updater are
Phases 7–8 in the roadmap.

## How the shell works (src-tauri/src/main.rs)

1. Spawns the sidecar from the bundle resource dir (dev fallback:
   `../../dist/jobcontext-backend/`).
2. Parses `JOBCONTEXT_PORT=<port>` from its stdout (stable format), then
   keeps draining stdout so the child never blocks on a full pipe.
3. Polls `GET /healthz` (raw TCP, no extra crates) up to 30 s; the window
   shows `splash/index.html` until then.
4. Navigates the webview to `http://127.0.0.1:<port>/app`.
5. On exit: `POST /desktop/shutdown`, waits up to 5 s for a clean exit,
   then kills — no orphaned backends, no SQLite lock contention.
6. Single-instance plugin: relaunching focuses the existing window instead
   of double-spawning against the same database.
