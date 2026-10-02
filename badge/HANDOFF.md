# Badge handoff — for a local Claude Code session

Paste-and-go context for continuing the GitHub Universe badge work on a Mac
with the badge physically attached. Written 2026-10-02 by the cloud session
that built this; it could never reach the hardware, which is why this exists.

**Branch:** `claude/jobcontext-github-badge-fw1b2q`
**Base:** current `main` as of `c2e9e3c` (PR #360)
**State:** complete, 2612 tests passing, never PR'd

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

## 2. Your actual job: run the probe, then fix `ui.py` from fact

`ui.py` contains three guesses that could not be checked without the badge.
`badge/probe.py` answers all of them. It writes nothing, connects to nothing,
and needs no `secrets.py`.

### Getting output

Cable must be **USB-C with data lines** — charge-only cables make the badge
look fine while never mounting.

```bash
ls /dev/cu.usbmodem*            # find the port
pip install mpremote            # if needed
mpremote run badge/probe.py     # runs WITHOUT copying; streams output
```

Have the user **hold UP** while it runs, so the button section proves the
mapping is live rather than merely present. Thonny also works if mpremote
fights you. Double-tap reset mounts the filesystem at `/Volumes/BADGER`.

### Decision tree from the output

**`display object` section**

- `badgeware.display` exists with `set_pen` / `create_pen` / `clear` / `text` /
  `rectangle` / `update` → the primary path in `ui.py` is correct. Verify each
  method name against the printed list; adapt `_pen()` if `create_pen` is
  absent (it already falls back to `set_pen(colour)`).
- Only `picographics` → **the fallback constant in `ui.py` is wrong.** It says
  `DISPLAY_TUFTY_2040`; this badge is a Tufty **2350**. The probe prints every
  `DISPLAY_*` constant — pick the right one.
- Neither → ask what the badge's own preloaded apps import, and rewrite
  `_import_firmware()` around that. Nothing outside `ui.py` should change.

**`font metrics` section — the important numbers**

`ui.CHAR_W = 8` is an estimate, and `measure_text` gives the truth. When you
correct it, remember **the widths exist in two places**:

- `badge/jobcontext/ui.py` — `CHAR_W`, `LINE_H`, and the `fit()` call sites
- `transport/http/routes/badge.py` — `_COMPANY_CHARS = 28`, `_ROLE_CHARS = 34`

The server pre-truncates so the firmware carries no layout maths, so a wrong
`CHAR_W` means the *server* is cutting strings at the wrong width. Fix both,
then re-run `tests/test_badge_api.py` — one test asserts `len(role) <= 34`
and will need its constant updated with you.

**`buttons` section**

Pin numbers in the PicoGraphics fallback (`UP=22 DOWN=6 A=7 B=8 C=9`) are
Tufty **2040** values. Confirm against what the probe reports before trusting
them on a 2350.

**`network / TLS` section**

If `ssl` has no `CERT_REQUIRED`, the badge's HTTPS is **unverified** — a
conference-WiFi MITM could lift the badge token. Not fatal (the token is
badge-scoped: search, enqueue, poll, nothing else) but worth telling Frank,
and an argument for revoking the token after the event.

---

## 3. The Bluetooth keyboard question

Originally requested; scaffolded but **not implemented**. `inputs.py` defines
a source interface, `best_available()` picks the richest working one, and
`BleKeyboardInput` reports unavailable so the app falls back to buttons.
Implementing its `available()` / `poll()` is the only change needed.

**The gate is in the probe.** If `bluetooth.BLE()` has no `gap_pair`, pairing
and bonding were not compiled into this firmware; keyboards refuse to send
reports over an unencrypted link, so it is a dead end — say so and stop.

If `gap_pair` IS present, there is a working reference to port:
`p4_ble_keyboard.py` in the **moybyte** project does the full sequence
(scan → connect/bond → discover HID service `0x1812` → subscribe to report
characteristics, with persistent bonding and autorepeat). Caveat: it targets
**ESP32-P4 on NimBLE** and needs two ESP-IDF flags. This badge is RP2350 +
CYW43439 on **BTstack**, so the protocol logic ports but the stack layer does
not.

**Before buying a keyboard:** it must be genuinely BLE, not Bluetooth Classic.
MicroPython has no Classic/BR-EDR support, and Classic-only devices never even
appear in a BLE scan. Cheapest check — scan with nRF Connect or LightBlue on a
phone; if the keyboard appears, it's BLE.

---

## 4. End-to-end run

Needs a badge-scoped token: Dashboard → API Keys → scope **"Badge only"**.
Copy `badge/jobcontext/secrets.example.py` to `secrets.py`, fill in
`WIFI_SSID`, `WIFI_PASSWORD`, `BASE_URL`, `BADGE_TOKEN`. Guest WiFi is wise —
both land in plain text on a filesystem anyone can mount.

```bash
cp -r badge/jobcontext /Volumes/BADGER/apps/
```

Then reset and pick *jobcontext* from the app menu.

| Screen | UP/DOWN | A | B | C |
|---|---|---|---|---|
| Search | move character strip | type highlighted char | backspace | search |
| Results | select | open actions | — | new search |
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

- `ui.py` firmware probe, `CHAR_W`, and fallback button pins — unverified
  (that's §2).
- BLE keyboard unimplemented (§3).
- A desktop simulator was offered and never built: a pygame/tkinter harness
  running the real modules in a 320×240 window. Largely moot now the hardware
  is in hand.
- No PR opened. Frank's call.
