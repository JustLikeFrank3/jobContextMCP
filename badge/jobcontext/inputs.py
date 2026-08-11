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

    def __init__(self):
        self.kb = OnScreenKeyboard()
        self._edges = _Edges(("UP", "DOWN", "A", "B", "C"), repeat=("UP", "DOWN"))

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
