# Badge handoff — for a local Claude Code session

Paste-and-go context for continuing the GitHub Universe badge work on a Mac
with the badge physically attached. Written 2026-10-02 by the cloud session
that built this; it could never reach the hardware, which is why this exists.

**Branch:** `claude/jobcontext-github-badge-fw1b2q`
**Base:** current `main` as of `c2e9e3c` (PR #360)
**State:** hardware-verified firmware; PR'd to qa 2026-10-02

---

## 0. Read this first: the branch was deleted once

The original commit was orphaned when this branch got deleted on GitHub, and
survived only as an unreferenced object recovered via the `.patch` endpoint.
**Do not delete this branch again** until the work is merged, and prefer
`--force-with-lease` over `--force` for anything that rewrites it. If it goes
missing again, the recovery route is:

```bash
curl -L https://github.com/JustLikeFrank3/jobContextMCP/commit/<sha>.patch | git am -3
```

Per `CLAUDE.md`: feature work goes **branch → PR → qa → main**, and **Frank
merges**. Nothing here has a PR yet; that is his call, not yours.

---

## 1. What already exists

**Server** — `transport/http/routes/badge.py`

| Endpoint | Purpose |
|---|---|
| `GET /api/badge/ping` | WiFi/token smoke test |
| `GET /api/badge/search?q=` | company *or* role over `job_queue`, topped up from `employer_directory` |
| `POST /api/badge/materials` | enqueues `badge_materials`, returns a work id |
| `GET /api/badge/work/{id}` | compact poll: status, what was made, one clipped error line |

`badge_materials` is an **async orchestrator**, not a second generator. P1
routed generation through `@tracked` (`tools/generate_work.py`) using
`run_now` — inline, because interactive callers wait. The badge can't wait, so
this kind is enqueued and calls the tracked generators from the dispatcher.
Each document still gets its own provenance-stamped row. Same shape
`capture_url` has with the assessment row it nests. **Don't "simplify" this
into a direct call** — that's the bug it was written to avoid.

**Scoped API keys** — `user_api_keys.scope` is `full` (default, unchanged
reach) or `badge` (`/api/badge/*` only). Enforced in
`UserDataContextMiddleware` (`transport/http/app.py`) *before any partition is
entered*, because the MCP mount never evaluates route dependencies — a check
living only in `require_authenticated_user` would leave every MCP tool
reachable by a badge key. A scoped refusal is **403, never 401**: the token is
authentic and re-authenticating cannot help.

The column is added by `_ensure_scope_column()` in `lib/api_keys.py`, **not**
`_MIGRATIONS` — `_apply_migrations` skips every statement containing
`ALTER TABLE` on the global DB, and `user_api_keys` is global, so a migration
entry would be ledgered as applied without ever running.

**Firmware** — `badge/jobcontext/`

```
__init__.py          app contract (init/update/on_exit) + state machine
ui.py                display & button shim — THE ONLY hardware-specific file
keyboard.py          on-screen character carousel
inputs.py            pluggable input sources (buttons now, BLE later)
api.py               /api/badge/* client
secrets.example.py   copy to secrets.py (gitignored)
probe.py             ../probe.py — hardware diagnostic, see below
```

---

## 2. Hardware facts (probed 2026-10-02 — no longer guesses)

`badge/probe.py` was run on a real badge. `ui.py` was rewritten from its
output; these are the facts it encodes:

- **Machine:** "GitHub Badger with RP2350", Pimoroni badgeware firmware,
  MicroPython 1.26. No PicoGraphics, no `tufty*` modules.
- **Display:** `badgeware.display` is a bare ST7789 (`update`/`backlight`/
  `command`). Drawing is `screen.brush = brushes.color(...)`, then
  `screen.draw(shapes.rectangle(...))` / `screen.text()`. **`screen` is
  160x120**, doubled onto the 320x240 panel — every coordinate is in 160x120.
- **Fonts:** proportional `.ppf` PixelFonts in `/system/assets/fonts/`,
  **ASCII-only** (any non-ASCII char draws as one fallback box). `ui.fit()`
  measures pixels; `ui._ascii()` folds "…", "—", accents before drawing. A
  fixed `CHAR_W` cannot be right, so the server's `_COMPANY_CHARS` /
  `_ROLE_CHARS` are now payload caps only — the badge does the real fitting.
- **Buttons:** `io.BUTTON_* in io.held`, refreshed by `run()` each frame.
  Active-low pins, confirmed live by holding UP during the probe.
- **Frame loop:** `run(update)` pushes `screen` after every update, so
  `ui.flip()` is a no-op; `ui.present()` (`display.update()`) is for frames
  drawn outside the loop (splash/status before a blocking call).
- **TLS:** `ssl.CERT_REQUIRED` exists, but MicroPython `requests` wraps the
  socket without a verifying context — treat badge HTTPS as **unverified**.
  The token is badge-scoped for exactly this reason; revoke it after events.

### REPL gotcha

Ctrl-C at the launcher menu (which `mpremote` sends on connect) makes
badgeware's `run()` return `None`; `main.py` then does
`sys.path.insert(0, None)` and **every subsequent `import` fails** with
`TypeError: can't convert 'NoneType' object to str`. Fix in-session with
`sys.path[:] = [p for p in sys.path if p is not None]`, or just reset.
Use `mpremote ... resume` to avoid the soft reset re-entering the menu.

---

## 3. The Bluetooth keyboard question — closed

The probe found **no `gap_pair`** on `bluetooth.BLE()`: pairing/bonding is
not compiled into this firmware, and keyboards refuse to send HID reports
over an unencrypted link. Dead end on stock firmware; buttons only.
`BleKeyboardInput` stays as the seam if a custom firmware build ever adds it.

---

## 4. Installing

`/system` (where apps live) is **read-only to MicroPython**, so mpremote
cannot install. Put the badge in USB-drive mode (double-tap reset → mounts
`/system` as `/Volumes/BADGER`), then:

```bash
cp badge/jobcontext/secrets.example.py badge/jobcontext/secrets.py   # fill in
python3 badge/install.py            # --dry-run to preview, --restore to undo
```

The launcher only shows apps in a hard-coded list in `apps/menu/__init__.py`
on a 3x2 grid the six stock apps fill, so the installer swaps **gallery's**
slot for jobcontext (override with `--remove`), backs up the menu and the
removed app to `~/badge-backups/<stamp>/`, copies the app + `icon.png`, and
ejects. Re-runs only refresh app files and make no backup.

The token must be **"Badge only"** scope — which only exists once this
branch is deployed. A full-scope key on a mountable drive is your whole job
search.

| Screen | UP/DOWN | A | B | C |
|---|---|---|---|---|
| Search | move character strip | type highlighted char | backspace | search |
| Results | select (scrolls, 3 visible) | open actions | — | new search |
| Actions | resume / cover letter / both | generate | — | back |
| Working | — | — | — | stop waiting |

---

## 5. Tests

```bash
# both provider configs — CI sets LLM_PROVIDER=foundry
LLM_PROVIDER=foundry python -m pytest tests/ -q
env -u LLM_PROVIDER python -m pytest tests/ -q

# the badge surface specifically
python -m pytest tests/test_badge_api.py tests/test_badge_firmware.py -q

# full-SQLite config
USE_SQLITE=1 SQLITE_ONLY=1 python -m pytest tests/test_badge_api.py -q
```

Last full run on this branch: **2612 passed, 17 skipped**. Python **3.12**
(3.11 cannot parse `tools/certification.py` — backslash in an f-string).

`tests/test_badge_firmware.py` drives the **real** state machine against a
fake `ui`/`api`, so most firmware logic is testable with no badge attached.
Two traps if you extend it:

- `_tap()` runs a *released* frame before the pressed one. Edge detection only
  fires low→high, so without that gap two taps of one button read as a hold.
- Polling is throttled to `_POLL_MS = 2000`; use `ui_.advance_ms()` to move the
  simulated clock rather than calling `update()` again.

There is a regression test for the button re-arm on screen changes — the OSK
and `_edge()` track edges separately, so the C press that submits a search was
still held when RESULTS first read it and bounced straight back. `_go()` exists
to fix that; don't bypass it with a bare `state = ...` assignment.

---

## 6. Known gaps

- Not yet run end-to-end against a deployed server (the badge routes were
  never deployed; first attempt 404'd at `/api/badge/ping`).
- Badge HTTPS is unverified (see §2). The 2026-10-25 pass added a
  `TLS_VERIFIED` constant to `api.py` and a note in `secrets.example.py`;
  the fix needs a MicroPython build with `ssl.CERT_REQUIRED`.

---

## 7. 2026-10-25 fixes (post-hardware-death)

The badge died of memory exhaustion 2026-10-23. PR #396 (already in qa) is
the fix: 66 KB → 104 KB free after init, measured on hardware. The badge
itself is currently unbootable (bootrom works, firmware doesn't execute —
likely the 12 MHz crystal); a replacement is expected for the 2026
conference.

Changes in this pass:

- **`on_exit` cleanup** — drops the saver's Tetris game + QR and releases
  api.py's 40KB TLS reserve, then `gc.collect()`. The next app gets a clean
  heap.
- **Home button exit** — `HOME` added to `_BUTTONS` and `ButtonInput`'s
  edge detection. `update()` checks `_home_pressed()` first and `_go(SEARCH)`
  on any screen. Whether the launcher intercepts Home first is untested on
  the new hardware.
- **Battery indicator** — `ui.header()` takes `battery` and `charging`
  params; every screen shows a 16×8 icon top-right. Sampled every 30s so the
  ADC read (10 samples) doesn't stall the frame loop.
- **BLE keyboard** — docstring updated with the 2026-10-25 probe: still no
  `gap_pair` in the firmware. The `p4_ble_keyboard.py` reference targets
  ESP32-P4/NimBLE, not RP2350/BTstack.
- **TLS verification** — `api.py` now checks `ssl.CERT_REQUIRED` at import
  and sets `TLS_VERIFIED`. `False` on the current build; the badge-scoped
  token remains the mitigation.

### Traps — things an edit will plausibly break

**1. `_go()` is not decoration.** Every state change must go through it,
never a bare `state = ...`. The on-screen keyboard and `_edge()` track
button edges separately, so without re-arming, the `C` press that submits a
search is still held when the results screen reads it and bounces straight
back. There is a regression test.

**2. The test fixture injects fakes under package-qualified names.**
`spec_from_file_location` on an `__init__.py` makes `badgeapp` a real
package, so `from . import api` resolves and the flat `sys.modules["api"]`
entry is *not* what the app picks up. The fixture seeds `badgeapp.api` /
`badgeapp.ui` before `exec_module`. Do not "simplify" that back to the flat
names — nine tests would silently start exercising the real `api.py` against
the stdlib `secrets` module and still pass.

**3. `.py` shadows `.mpy`.** MicroPython imports `name.py` before `name.mpy`,
so `install.py` deletes stale `.py` modules. Leaving one behind silently
reverts that module to the slow, memory-hungry path.

**4. mpy-cross must emit mpy v6.3** (MicroPython 1.26). `install.py` checks
before touching the badge; do not loosen that check.

**5. The 40 KB reserve in `api.py` is load-bearing.** Tetris fragments the
heap with small long-lived objects, so TLS handshakes failed with `ENOMEM`
despite >100 KB free. The reserve is grabbed at import while the heap is
clean and released immediately before each request. Removing it breaks
background polling only when the screen saver is running — which no test
will catch. `on_exit` releases it; it is re-taken on the next request.

**6. `badge_materials` is an async orchestrator, not a generator.** It calls
the `@tracked` generators from the dispatcher so the badge gets one id to
poll. Do not collapse it into a direct call; see `HANDOFF.md`.

**7. Battery indicator is drawn in `ui.header()`, not by the app.** Every
`ui.header()` call passes `_battery_level` and `_battery_charging`. Adding a
new screen means passing them too — or the icon vanishes on that screen.

**8. Home button is in `_BUTTONS` and `ButtonInput._edges`.** Removing it
from either means the exit gesture stops working. `_home_pressed()` calls
`_edge("HOME")`, which needs `_prev_buttons["HOME"]` to exist.

### The one unmerged commit

`be9a2ec` makes `api.py`'s `network` and `requests` imports safe. MonaOS
imports an app's module to launch it, so an `ImportError` at module scope
takes down the *launcher*, not the app — a blank screen indistinguishable
from dead hardware. The `secrets` case was already handled; these were the
last two holes. It has no PR yet.

### Known gaps (2026-10-25)

- **BLE keyboard** — scaffolded in `inputs.py`, not implemented. The gate is
  whether `bluetooth.BLE()` exposes `gap_pair`; without pairing/bonding
  compiled in, no keyboard will send reports. `badge/probe.py` answers it.
  A working reference exists (`p4_ble_keyboard.py` in the moybyte project)
  but targets ESP32-P4 on NimBLE; this badge is RP2350 on BTstack, so the
  protocol logic ports and the stack layer does not.
- **TLS verification** — check whether `ssl` exposes `CERT_REQUIRED` on this
  firmware. If not, badge HTTPS is unverified and the token is liftable on
  hostile WiFi. Badge-scoped, so bounded, but revoke it after an event.
- **Battery indicator** — untested on the replacement badge. The ADC read
  assumes `badge.battery_level()` exists; if the firmware build differs,
  `_poll_battery()` catches `AttributeError` and hides the icon.
- **Home button exit** — untested. If the launcher intercepts Home first,
  `_home_pressed()` never fires. If it doesn't, the app exits to SEARCH and
  the launcher takes over from there.
