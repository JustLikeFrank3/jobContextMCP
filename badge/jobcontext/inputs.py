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

  ButtonInput  — the pads (2026) or buttons (Tufty/2025) driving an
                 on-screen grid keyboard.
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

try:
    from . import ui
    from .keyboard import DELETE, SEARCH, SPACE, OnScreenKeyboard
except ImportError:
    import ui
    from keyboard import DELETE, SEARCH, SPACE, OnScreenKeyboard

# Held d-pad repeat: first repeat after _REPEAT_DELAY ms, then every
# _REPEAT_RATE ms, so crossing the grid does not take ten separate taps.
_REPEAT_DELAY = 400
_REPEAT_RATE = 110

_MOVES = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}


class TextInput:
    """Interface every input source implements."""

    name = "input"

    def available(self):
        return False

    def poll(self):
        """Return a list of events since the last call."""
        return []

    def draw(self, text_so_far):
        """Optionally render the source's own UI (the OSK needs this)."""


class ButtonInput(TextInput):
    """The pads or buttons driving an on-screen grid keyboard.

    Written against logical actions; ui.py maps them onto 2026 pads or onto
    a Tufty's A/B/C/UP/DOWN (where SELECT is a tap of B and BACK a hold).

    Mapping:
        d-pad   — move the cursor, repeating while held
        SELECT  — press the highlighted key
        BACK    — delete one character
        MENU    — search now, from anywhere on the grid

    Edge detection is the firmware's: ui.pressed() is true only on the frame
    a pad goes down, so a press that ends one screen cannot also actuate the
    next one.
    """

    name = "buttons"

    def __init__(self):
        self.kb = OnScreenKeyboard()
        self._next_repeat = {}

    def available(self):
        return True

    def poll(self):
        events = []
        now = ui.ticks()
        for name, (d_row, d_col) in _MOVES.items():
            if ui.pressed(name):
                self.kb.move(d_row, d_col)
                self._next_repeat[name] = now + _REPEAT_DELAY
            elif ui.held(name):
                due = self._next_repeat.get(name)
                if due is not None and now >= due:
                    self.kb.move(d_row, d_col)
                    self._next_repeat[name] = now + _REPEAT_RATE
            else:
                self._next_repeat.pop(name, None)

        if ui.pressed("SELECT"):
            key = self.kb.current()
            if key == SPACE:
                events.append(("char", " "))
            elif key == DELETE:
                events.append(("back",))
            elif key == SEARCH:
                events.append(("submit",))
            else:
                events.append(("char", key))
        if ui.pressed("BACK"):
            events.append(("back",))
        if ui.pressed("MENU"):
            events.append(("submit",))
        return events

    def draw(self, text_so_far):
        self.kb.draw(text_so_far)


class BleKeyboardInput(TextInput):
    """A paired Bluetooth keyboard. Not implemented — see the module docstring.

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

    Ordered by preference, filtered by reality — so the day BleKeyboardInput
    starts working, it is chosen automatically.
    """
    for source in (BleKeyboardInput(), ButtonInput()):
        if source.available():
            return source
    return ButtonInput()
