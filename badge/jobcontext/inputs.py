"""Pluggable text input for the badge.

The app never asks "which buttons are down" — it asks an input source for
*events*.  That indirection is the whole point: a Bluetooth keyboard and the
on-screen keyboard produce the same four events, so the app's state machine
does not change when the input method does.

Events are tuples:
    ("char", "A")   a character was entered
    ("back",)       delete one character
    ("submit",)     run the search
    ("cancel",)     back out

Two sources live here:

  ButtonInput  — the five hardware buttons driving an on-screen keyboard.
                 Always available, works on a plane, needs no pairing.

  BleKeyboardInput — a real Bluetooth keyboard.  NOT implemented, and the
                 docstring explains exactly what it would take, because the
                 gap is not laziness: it needs an HID-over-GATT *host*
                 (central) stack, and MicroPython's BLE HID ecosystem is
                 entirely peripheral-side — libraries that let a board
                 pretend to BE a keyboard.  Being a keyboard host means
                 scanning, connecting, discovering service 0x1812, reading
                 and parsing the report map, subscribing to report
                 notifications, and holding an encrypted bonded link (nearly
                 every keyboard refuses to send reports over an unencrypted
                 one).  MicroPython's pairing/bonding support is build-flag
                 gated, so step one is confirming the badge's firmware was
                 compiled with it at all.
"""

import time

try:
    from . import ui
    from .keyboard import OnScreenKeyboard
except ImportError:
    import ui
    from keyboard import OnScreenKeyboard

# Repeat behaviour for held UP/DOWN: first repeat after _REPEAT_DELAY, then
# every _REPEAT_RATE, so scrolling to 'W' does not take twenty presses.
_REPEAT_DELAY = 400
_REPEAT_RATE = 90


class _Edges:
    """Debounced press/repeat detection over ui.pressed()."""

    def __init__(self, names, repeat=()):
        self._down = {n: False for n in names}
        self._since = {n: 0 for n in names}
        self._next = {n: 0 for n in names}
        self._repeat = set(repeat)

    def rearm(self):
        """Treat every currently-held button as already seen.

        Called on a screen change: without it, the press that *left* the last
        screen is still down when this one starts reading, reads as a fresh
        press, and actuates whatever the new screen has bound to it.
        """
        for name in self._down:
            self._down[name] = ui.pressed(name)

    def poll(self):
        """Return the list of button names that 'fired' this frame."""
        fired = []
        now = time.ticks_ms()
        for name in self._down:
            is_down = ui.pressed(name)
            if is_down and not self._down[name]:
                fired.append(name)
                self._since[name] = now
                self._next[name] = time.ticks_add(now, _REPEAT_DELAY)
            elif is_down and name in self._repeat:
                if time.ticks_diff(now, self._next[name]) >= 0:
                    fired.append(name)
                    self._next[name] = time.ticks_add(now, _REPEAT_RATE)
            self._down[name] = is_down
        return fired


class TextInput:
    """Interface every input source implements."""

    name = "input"
    # Footer legend for the search screen. It belongs to the source rather
    # than the screen: the badge has no key labels, and "A type B del" is a
    # lie the moment the characters arrive from somewhere that isn't buttons.
    hint = ""

    def available(self):
        return False

    def poll(self):
        """Return a list of events since the last call."""
        return []

    def draw(self, text_so_far):
        """Optionally render the source's own UI (the OSK needs this)."""

    def rearm(self):
        """Discard any in-flight press state after a screen change."""


class ButtonInput(TextInput):
    """Five buttons, one on-screen keyboard.

    Mapping (no left/right button exists, which is why entry is a carousel
    rather than a grid):
        UP / DOWN — move through the character strip, accelerating when held
        A         — type the highlighted character
        B         — backspace
        C         — search now
    """

    name = "buttons"
    hint = "U/D pick  A type  B del  C search"

    def __init__(self):
        self.kb = OnScreenKeyboard()
        self._edges = _Edges(("UP", "DOWN", "A", "B", "C", "HOME"), repeat=("UP", "DOWN"))

    def available(self):
        return True

    def poll(self):
        events = []
        for button in self._edges.poll():
            if button == "UP":
                self.kb.move(-1)
            elif button == "DOWN":
                self.kb.move(1)
            elif button == "A":
                events.append(("char", self.kb.current()))
            elif button == "B":
                events.append(("back",))
            elif button == "C":
                events.append(("submit",))
        return events

    def draw(self, text_so_far):
        self.kb.draw(text_so_far)

    def rearm(self):
        self._edges.rearm()


class I2CKeyboardInput(TextInput):
    """A wired keyboard on the qwiic port (M5Stack CardKB / CardKB2).

    This is the route that survived. BLE HID needs an encrypted link, which
    needs bonding, which this firmware does not have — so a wired bus is the
    only way to get real keys without a custom build.

    Protocol is as simple as it gets: read one byte, 0 means no key, anything
    else is the character code. The keyboard handles its own Fn/Sym layers,
    so what arrives is already the character the user meant.

    The address is *scanned for*, not hardcoded. The original CardKB answers
    on 0x5F, but the CardKB2 is a different chip (ESP32-C61) whose address is
    not documented anywhere reachable — and a keyboard that only works after
    someone edits a constant is a keyboard that does not work. Set
    KEYBOARD_I2C_ADDR in secrets.py to override.

    Pins are not guessed. Nothing in this codebase knows which GPIO the qwiic
    port uses, and driving arbitrary pins as a bus picks fights with whatever
    else is on them, so this uses a firmware-provided bus or the default bus
    ids only. badge/probe.py reports what is really there.
    """

    name = "i2c-keyboard"
    hint = "type  ENTER search  ESC back"

    # Byte values that mean something other than "a character".
    _BACKSPACE = 0x08
    _TAB = 0x09
    _ENTER = (0x0A, 0x0D)
    _ESC = 0x1B

    # The original CardKB drops keys when polled flat out; a short floor
    # between reads costs nothing at frame rate and fixes it.
    _MIN_INTERVAL_MS = 20

    def __init__(self, i2c=None, address=0):
        self._i2c = i2c
        self._address = address
        self._last_read = 0
        self._checked = False

    # ── discovery ──────────────────────────────────────────────────────────

    def _candidate_buses(self):
        """Buses worth scanning, most authoritative first."""
        buses = []
        for mod_name in ("badgeware", "qwiic", "board"):
            try:
                mod = __import__(mod_name)
            except ImportError:
                continue
            for attr in ("i2c", "I2C", "qwiic"):
                bus = getattr(mod, attr, None)
                if bus is not None and hasattr(bus, "scan"):
                    buses.append(bus)
        try:
            import machine
        except ImportError:
            return buses
        if not hasattr(machine, "I2C"):
            return buses
        for bus_id in (0, 1):
            try:
                buses.append(machine.I2C(bus_id))
            except Exception:  # noqa: BLE001 — an unusable bus id is not an error
                continue
        return buses

    def _configured_address(self):
        try:
            from . import secrets  # type: ignore
        except ImportError:
            try:
                import secrets  # type: ignore
            except ImportError:
                return 0
        return int(getattr(secrets, "KEYBOARD_I2C_ADDR", 0) or 0)

    def _discover(self):
        """Find a keyboard on some bus. Returns True once self._i2c is set."""
        wanted = self._configured_address()
        for bus in self._candidate_buses():
            try:
                found = bus.scan()
            except Exception:  # noqa: BLE001 — a bus that will not scan is no bus
                continue
            if wanted and wanted in found:
                self._i2c, self._address = bus, wanted
                return True
            if 0x5F in found:  # CardKB family's documented address
                self._i2c, self._address = bus, 0x5F
                return True
            # Exactly one unknown device on an otherwise empty bus is almost
            # certainly the thing someone just plugged into the qwiic port.
            # More than one and we decline to guess: set KEYBOARD_I2C_ADDR.
            if len(found) == 1:
                self._i2c, self._address = bus, found[0]
                return True
        return False

    def available(self):
        """True if a keyboard answered. Cached: scanning every frame is silly,
        and a keyboard plugged in mid-session can wait for the next start."""
        if self._i2c is not None and self._address:
            return True
        if self._checked:
            return False
        self._checked = True
        try:
            return self._discover()
        except Exception:  # noqa: BLE001 — no keyboard is a normal outcome
            return False

    # ── reading ────────────────────────────────────────────────────────────

    def poll(self):
        if not self.available():
            return []
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_read) < self._MIN_INTERVAL_MS:
            return []
        self._last_read = now
        try:
            data = self._i2c.readfrom(self._address, 1)
        except Exception:  # noqa: BLE001 — a yanked cable must not crash the app
            return []
        if not data or data[0] == 0:
            return []
        return self._event_for(data[0])

    def _event_for(self, code):
        if code == self._BACKSPACE:
            return [("back",)]
        if code in self._ENTER or code == self._TAB:
            return [("submit",)]
        if code == self._ESC:
            return [("cancel",)]
        if 0x20 <= code <= 0x7E:
            return [("char", chr(code))]
        # Arrow keys and friends arrive as multi-byte or high codes; ignoring
        # them is better than typing a square into the search box.
        return []

    # ── drawing ────────────────────────────────────────────────────────────

    def draw(self, text_so_far):
        """Entry line only — a real keyboard needs no character carousel."""
        ui.rect(0, 31, ui.WIDTH, 18, (12, 18, 30))
        if text_so_far:
            ui.text(ui.fit_tail(text_so_far + "_", ui.WIDTH - 8, 2), 4, 34, ui.WHITE, 2)
        else:
            ui.text("type a company", 4, 34, ui.DIM, 2)
        ui.text("keyboard " + hex(self._address), 4, 62, ui.DIM, 1)


class BleKeyboardInput(TextInput):
    """A paired Bluetooth keyboard. Not implemented — see the module docstring.

    Probed on hardware 2026-10-02 and again 2026-10-25: the stock firmware
    has no gap_pair, so bonding is not compiled in and this cannot work
    without a custom build. A working reference exists (p4_ble_keyboard.py
    in the moybyte project) but targets ESP32-P4 on NimBLE; this badge is
    RP2350 on BTstack, so the protocol logic ports and the stack layer does
    not.

    Kept as a real class rather than a TODO comment so the wiring is already
    in place: implement available()/poll() here and the app picks it up with
    no other change. Until then it reports unavailable and the app silently
    falls back to the buttons.
    """

    name = "ble-keyboard"

    def available(self):
        return False

    def poll(self):
        return []


def best_available():
    """Return the richest input source this badge can actually offer.

    Ordered by preference, filtered by reality — so a keyboard on the qwiic
    port is used the moment one is plugged in, and the buttons take over the
    moment it is not. BLE stays first in the list so it wins automatically if
    a firmware with bonding ever ships.
    """
    for source in (BleKeyboardInput(), I2CKeyboardInput(), ButtonInput()):
        if source.available():
            return source
    return ButtonInput()
