# Copilot handoff — badge, current state

For GitHub Copilot in VS Code, 2026-10-25. Deep architecture lives in
[`badge/HANDOFF.md`](HANDOFF.md); this is what changed and what to do next.
Where the two disagree, this file is newer.

## Start here: you are probably on the wrong branch

```
main  fc96fb7   ← 13 commits BEHIND qa. Missing the fixes that revive the badge.
qa    2950930   ← has PR #396: screen saver, multi-network WiFi, memory fixes
claude/jobcontext-github-badge-fw1b2q  be9a2ec  ← qa + 1 commit, no PR yet
```

`main` has the badge app and `install.py`, but **not** `screensaver.py`,
`tetris.py`, `contact.example.py`, nor the rewritten `api.py` / `ui.py` /
`__init__.py`. If the badge is dead and you are on `main`, that is why.

```bash
git fetch origin
git checkout claude/jobcontext-github-badge-fw1b2q   # qa + the import-safety fix
```

That branch is the newest complete state. Use `qa` instead only if you
specifically want to exclude the unmerged commit.

## Immediate task: get the badge running

The badge died of memory exhaustion, and PR #396 is the fix. Measured on the
hardware: free memory after init went from 66 KB to 104 KB.

```bash
python badge/install.py      # compiles with mpy-cross on the Mac, then copies
```

**Two files are gitignored and will NOT arrive with the pull.** Both must exist
before installing:

| File | From | Notes |
|---|---|---|
| `badge/jobcontext/secrets.py` | `secrets.example.py` | Now needs **`WIFI_NETWORKS`** (a list), not a single SSID |
| `badge/jobcontext/contact.py` | `contact.example.py` | Screen-saver contact card; absent means no saver |

`secrets.py` needs a **badge-scoped** token: Dashboard → API Keys → scope
"Badge only". A full-access key must never go on the badge — double-tapping
reset mounts it as a USB drive with `secrets.py` in plain text.

If the badge will not boot at all: hold **`Home`**, press and release
**`Reset`**, release `Home` → a drive named `RP2350` mounts → drag the firmware
`.uf2` from the badge repo's Releases. If that does not take, `flash_nuke.uf2`
wipes flash first. The RP2350 bootrom is in mask ROM, so this path survives
anything written to flash.

## Process — non-negotiable

From `CLAUDE.md`: feature work goes **branch → PR → qa → main**. Never commit
to `main`. Promotion is a separate `qa → main` PR after the qa deploy is green.
**Frank merges PRs.** A push to `qa` triggers `deploy.yml`, which deploys to
AKS — so do not push there casually.

`qa → main` promotion for PR #396 has not happened yet. That is Frank's call.

## Tests

**Python 3.12 required** — 3.11 cannot parse `tools/certification.py`
(backslash in an f-string).

```bash
LLM_PROVIDER=foundry python -m pytest tests/ -q     # CI's env
env -u LLM_PROVIDER python -m pytest tests/ -q      # run both when touching provider logic
python -m pytest tests/test_badge_firmware.py tests/test_badge_api.py \
                 tests/test_badge_install.py tests/test_badge_tetris.py -q
```

Last full run on the branch above: **2811 passed, 18 skipped**.

Most firmware logic is testable with no badge attached —
`tests/test_badge_firmware.py` drives the real state machine against a fake
`ui`/`api`.

## Traps — things an edit will plausibly break

**1. `_go()` is not decoration.** Every state change in
`badge/jobcontext/__init__.py` must go through it, never a bare
`state = ...`. The on-screen keyboard and `_edge()` track button edges
separately, so without re-arming, the `C` press that submits a search is still
held when the results screen reads it and bounces straight back. There is a
regression test.

**2. The test fixture injects fakes under package-qualified names.**
`spec_from_file_location` on an `__init__.py` makes `badgeapp` a real package,
so `from . import api` resolves and the flat `sys.modules["api"]` entry is
*not* what the app picks up. The fixture seeds `badgeapp.api` / `badgeapp.ui`
before `exec_module`. Do not "simplify" that back to the flat names — nine
tests would silently start exercising the real `api.py` against the stdlib
`secrets` module and still pass.

**3. `.py` shadows `.mpy`.** MicroPython imports `name.py` before `name.mpy`,
so `install.py` deletes stale `.py` modules. Leaving one behind silently
reverts that module to the slow, memory-hungry path.

**4. mpy-cross must emit mpy v6.3** (MicroPython 1.26). `install.py` checks
before touching the badge; do not loosen that check.

**5. The 40 KB reserve in `api.py` is load-bearing.** Tetris fragments the
heap with small long-lived objects, so TLS handshakes failed with `ENOMEM`
despite >100 KB free. The reserve is grabbed at import while the heap is clean
and released immediately before each request. Removing it breaks background
polling only when the screen saver is running — which no test will catch.

**6. `badge_materials` is an async orchestrator, not a generator.** It calls
the `@tracked` generators from the dispatcher so the badge gets one id to poll.
Do not collapse it into a direct call; see `HANDOFF.md`.

## The one unmerged commit

`be9a2ec` makes `api.py`'s `network` and `requests` imports safe. MonaOS
imports an app's module to launch it, so an `ImportError` at module scope takes
down the *launcher*, not the app — a blank screen indistinguishable from dead
hardware. The `secrets` case was already handled; these were the last two
holes. It has no PR yet.

## Known gaps

- **BLE keyboard** — scaffolded in `inputs.py`, not implemented. The gate is
  whether `bluetooth.BLE()` exposes `gap_pair`; without pairing/bonding
  compiled in, no keyboard will send reports. `badge/probe.py` answers it.
  A working reference exists (`p4_ble_keyboard.py` in the moybyte project) but
  targets ESP32-P4 on NimBLE; this badge is RP2350 on BTstack, so the protocol
  logic ports and the stack layer does not.
- **TLS verification** — check whether `ssl` exposes `CERT_REQUIRED` on this
  firmware. If not, badge HTTPS is unverified and the token is liftable on
  hostile WiFi. Badge-scoped, so bounded, but revoke it after an event.
