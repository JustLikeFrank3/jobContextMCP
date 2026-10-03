# jobcontext on the GitHub Universe badge

Search your job pipeline and queue tailored materials from the badge on your
lanyard. Type a company you just met, see what your own data says about them,
press a button, and a resume or cover letter is generated back on the server.

![flow](https://img.shields.io/badge/SEARCH-→_RESULTS_→_ACTIONS_→_WORKING-informational)

## The hardware

GitHub Universe 2025 handed out a **Pimoroni Tufty 2350 "Tufty Edition"** —
a custom-PCB Tufty with extra IR, preloaded apps and Pimoroni's badgeware
MicroPython firmware.

| | |
|---|---|
| MCU | RP2350B, dual Cortex-M33 @ 250MHz, 520KB SRAM |
| Memory | 16MB QSPI flash (XiP) + 8MB PSRAM |
| Display | 2.8" colour IPS LCD, 320×240 (apps draw at 160×120, doubled) |
| Wireless | Raspberry Pi RM2 (CYW43439) — WiFi b/g/n + Bluetooth 5.2 |
| Buttons | UP, DOWN, A, B, C |
| Other | IR receiver, phototransistor, qwiic port, 1000mAh LiPo |

## Install

1. **Mint a badge-scoped token.** Dashboard → API Keys → scope
   **"Badge only — conference badge"** → Generate. Copy it; it is shown once.

2. **Configure.** Copy `jobcontext/secrets.example.py` to
   `jobcontext/secrets.py` and fill in WiFi + the token. `secrets.py` is
   gitignored.

3. **Install.** One-time prerequisite — the installer precompiles the app
   (the badge runs out of memory compiling it from source itself):

   ```sh
   uv tool install "mpy-cross==1.26.*"   # or: pip install "mpy-cross==1.26.*"
   ```

   Then double-tap reset to mount the badge as a USB drive (it appears as
   `BADGER`), and:

   ```sh
   python3 badge/install.py          # --dry-run to preview first
   ```

   A plain `cp -r` is not enough: the launcher only shows apps named in a
   hard-coded list in `apps/menu/__init__.py`, on a 3x2 grid the six stock
   apps already fill. The installer gives jobcontext **gallery's** slot
   (`--remove <app>` to choose another), backs up what it changes to
   `~/badge-backups/`, and ejects. `--restore <backup>` undoes it.

4. **Reset** and pick *jobcontext* from the app menu.

## Using it

| Screen | UP / DOWN | A | B | C |
|---|---|---|---|---|
| Search | move the character strip | type the highlighted character | backspace | search |
| Results | select a result | open the actions menu | — | new search |
| Actions | resume / cover letter / both | generate | — | back |
| Working | — | — | — | stop waiting |

Text entry is a horizontal character carousel rather than a grid keyboard
because the badge has no left/right buttons — only UP, DOWN, A, B and C.
Holding UP or DOWN accelerates after 400ms.

## Screen saver: your contact card

Leave the badge on the jobcontext app and after `IDLE_SECONDS` (default 30)
with no button presses it turns into a name tag: your name, title and links on
the left, alternating every few seconds with a **QR code of the same details as
a vCard** (scan it to add you to contacts), and a self-playing game of Tetris
on the right. Any button wakes it; that press is swallowed, so waking with A
never also types a letter. It never covers the "generating" screen, and every
screen change restarts the idle clock so "ready" stays visible.

Copy `jobcontext/contact.example.py` to `jobcontext/contact.py` (gitignored),
fill it in, and re-run `install.py`. No `contact.py` means no screen saver.
Keep the fields short: every character makes the QR denser and harder to scan
off a 2.8" screen.

## Why the token is scoped

Anyone can mount this badge's filesystem by double-tapping reset and plugging
in a USB-C cable, and `secrets.py` is plain text. A badge-scoped key can do
exactly three things — search, queue a generation, poll that generation — and
is refused everywhere else in the API, including the MCP surface. Never put a
full-access key on a device you wear.

Use guest WiFi if you can, for the same reason.

## About Bluetooth keyboards

The original design called for pairing a Bluetooth keyboard to the badge for
fast text entry. That is not implemented, and the reason is structural rather
than incidental: it needs the badge to act as an HID-over-GATT **host**
(scan → connect → discover service `0x1812` → parse the report map →
subscribe to report notifications → hold an encrypted bonded link, because
essentially every keyboard refuses to send reports over an unencrypted one).

Every MicroPython BLE HID library in the wild is the *peripheral* side — code
that lets a board pretend to *be* a keyboard. There is no host stack to drop
in, and MicroPython's pairing/bonding support is build-flag gated, so step one
is confirming badgeware was even compiled with it.

The app is built so this can land without touching the state machine:
`inputs.py` defines a source interface, `best_available()` picks the richest
working one, and `BleKeyboardInput` is already wired in and reporting
unavailable. Implement `available()` and `poll()` there and the badge starts
using it automatically.

Two cheaper alternatives, if the goal is just faster typing: have the phone
serve as the keyboard over the badge's own WiFi, or invert the BLE direction
so the badge is a peripheral the existing Expo app writes into — that
direction MicroPython supports well.

## Layout

```
badge/jobcontext/
  __init__.py          app contract (init/update/on_exit) + state machine
  ui.py                display & button shim — the ONLY hardware-specific file
  keyboard.py          on-screen character carousel
  inputs.py            pluggable input sources (buttons now, BLE later)
  api.py               /api/badge/* client
  secrets.example.py   copy to secrets.py
```

`ui.py` adapts to whichever drawing API the firmware exposes. If the badge's
API differs from what it probes for, that is the one file to correct.

The state machine is tested on the host, against fake hardware, in
`tests/test_badge_firmware.py` — no badge required to run them.

## The probe

`badge/probe.py` asks the badge what its firmware actually exposes. It was run
on real hardware on 2026-10-02 and `ui.py` was rewritten from its output —
`badge/HANDOFF.md` §2 has the findings. Re-run it if a firmware update
changes things:

```sh
mpremote resume run badge/probe.py   # hold UP while it runs
```

It writes nothing, connects to nothing, and needs no `secrets.py`. The
headline results: drawing is badgeware's 160x120 `screen` (no PicoGraphics),
fonts are proportional and ASCII-only (so `ui.fit()` measures pixels), and
`bluetooth.BLE()` has **no `gap_pair`** — the Bluetooth-keyboard path is a
dead end on stock firmware.
