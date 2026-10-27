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
direction MicroPython supports well. Note the blocker is specific to HID: a
*custom* GATT characteristic needs no encryption and so no bonding, which is
why the phone route stays open while keyboards do not.

## Typing on your phone (no hardware)

The route that needs nothing bought. When your phone is the hotspot — already
the recommended network, because conference WiFi puts a captive portal in
front of the API — the phone and the badge are on the same network by
construction. The badge serves a one-field form; you type, submit, and the
search runs on the badge.

```sh
python badge/install_phone.py     # phone keyboard ON
python badge/install.py           # phone keyboard OFF — the way back
```

The badge shows its address on the search screen once WiFi is up. The buttons
keep working throughout: the phone is an addition, not a replacement, and the
carousel is what you fall back to when the phone is in a pocket.

**`install.py` is a real fallback.** It deletes the generated `features.py`,
so reinstalling with it gives you the buttons-only build rather than the same
build with a stale flag. Set `PHONE_KEYBOARD` in `secrets.py` to flip the
switch without reinstalling.

Anyone on the same network can type into the badge. On a personal hotspot
that is you and nobody else. On a shared network a stranger could run
searches against your pipeline — they cannot read the results, which render
on the badge in your hand, but do not switch this on at a conference and walk
away from it.

## A wired keyboard (this one works)

With BLE closed, the qwiic port is the way to real keys. An **M5Stack CardKB
or CardKB2** speaks plain I2C: read one byte, `0` means no key, anything else
is the character code, and the keyboard handles its own Fn/Sym layers. Plug it
in and `best_available()` picks it up — no configuration, no pairing.

Wiring, in order of what will bite you:

- **Connect three wires: GND, SDA, SCL. Leave VCC disconnected.** The CardKB2
  wants 5 V and the badge's qwiic supplies 3.3 V; feeding its 5 V into the
  badge's rail is the one way to damage something here. Power the keyboard
  from its own USB-C.
- **GND is not optional.** It is the wire people skip when each device has its
  own supply, and then nothing works.
- **Connectors differ**: HY2.0-4P (2.0 mm) on the keyboard, JST-SH (1.0 mm) on
  the badge. You need an adapter cable, or a Grove→Dupont→Qwiic chain for
  bring-up — the loose-wire version makes omitting VCC trivial.
- **If the scan finds nothing, swap SDA and SCL.** Harmless; the bus just
  stays quiet. Keep the run short — I2C over long floppy jumpers gets flaky,
  and dropping to 100 kHz helps before you suspect anything else.

The CardKB2 has four modes (`Fn + Sym + 1..4`). **I2C is mode 1 and the
factory default.** Its BLE HID mode is the same dead end as any other BLE
keyboard, and ESP-NOW cannot reach a CYW43439 at all.

Run `badge/probe.py` first: it reports whether `machine.I2C` exists, which
buses work, and what is on them. If the firmware has no I2C, this route is
closed too and nothing needs buying.

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
