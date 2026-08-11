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
| Display | 2.8" colour IPS LCD, 320×240 |
| Wireless | Raspberry Pi RM2 (CYW43439) — WiFi b/g/n + Bluetooth 5.2 |
| Buttons | UP, DOWN, A, B, C |
| Other | IR receiver, phototransistor, qwiic port, 1000mAh LiPo |

## Install

1. **Mint a badge-scoped token.** Dashboard → API Keys → scope
   **"Badge only — conference badge"** → Generate. Copy it; it is shown once.

2. **Configure.** Copy `jobcontext/secrets.example.py` to
   `jobcontext/secrets.py` and fill in WiFi + the token. `secrets.py` is
   gitignored.

3. **Copy to the badge.** Double-tap reset to mount it as a USB drive
   (it appears as `BADGER`), then drop the app in:

   ```sh
   cp -r badge/jobcontext /Volumes/BADGER/apps/
   ```

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
