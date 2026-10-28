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
    """Hardware buttons driving an on-screen keyboard carousel.

    Two layouts. The original badge has no left/right buttons:
        UP / DOWN — move through the character strip, accelerating when held
        A — type the highlighted character; B — backspace; C — search
    The BadgeOS badge's bottom row is <, >, Enter, so movement goes there:
        < / > — move the strip; Enter — type; UP — backspace; DOWN — search
    """

    name = "buttons"
    hint = "U/D pick  A type  B del  C search"

    def __init__(self):
        self.kb = OnScreenKeyboard()
        if ui.badgeos():
            # A/B are the physical </> here — they move, so they repeat.
            self._edges = _Edges(("UP", "DOWN", "A", "B", "C", "HOME"), repeat=("A", "B"))
            self._actions = {"A": -1, "B": 1, "C": "char", "UP": "back", "DOWN": "submit"}
            self.hint = "</> pick  ENT type  U del  D search"
        else:
            self._edges = _Edges(("UP", "DOWN", "A", "B", "C", "HOME"), repeat=("UP", "DOWN"))
            self._actions = {"UP": -1, "DOWN": 1, "A": "char", "B": "back", "C": "submit"}

    def available(self):
        return True

    def poll(self):
        events = []
        for button in self._edges.poll():
            action = self._actions.get(button)
            if isinstance(action, int):
                self.kb.move(action)
            elif action == "char":
                events.append(("char", self.kb.current()))
            elif action == "back":
                events.append(("back",))
            elif action == "submit":
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


class WebInput(ButtonInput):
    """Type on your phone; the badge serves the form.

    The buttons keep working — this *extends* ButtonInput rather than
    replacing it, because the phone is an addition and the carousel is what
    you fall back to when the phone is in a pocket or the network drops.

    Why this route exists: BLE HID needs bonding the firmware does not have,
    and the wired I2C keyboard needs parts and a cable chain. This needs
    nothing. When the phone is the hotspot — which is already the recommended
    network, because conference WiFi puts a captive portal in front of the
    API — the phone and the badge are on the same network by construction.

    Binding is lazy. init() picks the input source *before* WiFi comes up, so
    there is no socket to open yet; poll() binds on the first frame after the
    interface has an address, and gives up gracefully if it cannot.

    Anyone on the same network can type into the badge. On a personal hotspot
    that is you and nobody else, which is the intended setup. Do not use this
    on a shared conference network expecting privacy — the form takes a
    search string, so the cost is a stranger searching your pipeline, but it
    is not nothing.
    """

    name = "web"
    hint = "type on your phone  C search"
    port = 80

    def __init__(self):
        ButtonInput.__init__(self)
        self._sock = None
        self._conn = None
        self._address = ""
        self._bind_failed = False

    # ── availability ───────────────────────────────────────────────────────

    def available(self):
        """Optimistic: the modules exist. The socket cannot be opened yet
        because WiFi is not up when sources are chosen."""
        try:
            import network  # noqa: F401
            import socket  # noqa: F401
        except ImportError:
            return False
        return True

    def _ip(self):
        try:
            import network

            wlan = network.WLAN(network.STA_IF)
            if not wlan.isconnected():
                return ""
            return wlan.ifconfig()[0]
        except Exception:  # noqa: BLE001 — no address is a normal early state
            return ""

    def _ensure_bound(self):
        """Open the listening socket once the interface has an address."""
        if self._sock is not None or self._bind_failed:
            return self._sock is not None
        address = self._ip()
        if not address:
            return False
        try:
            import socket

            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.listen(1)
            sock.setblocking(False)
        except Exception:  # noqa: BLE001 — port taken, no sockets, whatever
            self._bind_failed = True
            return False
        self._sock, self._address = sock, address
        return True

    # ── accepting ──────────────────────────────────────────────────────────

    def _accept(self):
        """Stash one pending connection. True if we are holding one.

        Separate from poll() so the screen saver can ask 'is someone typing?'
        without consuming the request — see pending().
        """
        if self._conn is not None:
            return True
        if not self._ensure_bound():
            return False
        try:
            conn, _addr = self._sock.accept()
        except Exception:  # noqa: BLE001 — EAGAIN every frame nobody is typing
            return False
        self._conn = conn
        return True

    def pending(self):
        """True when a phone has knocked. The app treats this as activity, so
        the screen saver does not start — or stay up — while someone types."""
        try:
            return self._accept()
        except Exception:  # noqa: BLE001
            return False

    # ── serving ────────────────────────────────────────────────────────────

    def poll(self):
        events = ButtonInput.poll(self)
        if not self._accept():
            return events
        conn, self._conn = self._conn, None
        try:
            events.extend(self._serve(conn))
        except Exception:  # noqa: BLE001 — a half-open phone must not crash us
            pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        return events

    def _serve(self, conn):
        try:
            conn.settimeout(0.4)  # the only blocking moment, and only on a hit
            raw = conn.recv(512)
        except Exception:  # noqa: BLE001 — phone opened and wandered off
            return []
        text = _as_text(raw)
        query = _query_param(text, "q")
        if query:
            conn.send(_PAGE % ("searching for " + _escape(query)))
            # Replace rather than append: the phone sends the whole string, and
            # concatenating onto whatever the buttons left behind is never what
            # anyone meant.
            return [("set", query), ("submit",)]
        conn.send(_PAGE % "")
        return []

    # ── drawing ────────────────────────────────────────────────────────────

    def draw(self, text_so_far):
        ButtonInput.draw(self, text_so_far)
        if self._sock is not None and self._address:
            ui.text("http://" + self._address, 4, ui.HEIGHT - 30, ui.ACCENT, 1)
        elif self._bind_failed:
            ui.text("phone typing unavailable", 4, ui.HEIGHT - 30, ui.DIM, 1)
        else:
            ui.text("phone typing: waiting for wifi", 4, ui.HEIGHT - 30, ui.DIM, 1)


# A whole page in one string: the badge has no filesystem to spare and no
# templating. autofocus + autocapitalize off means you land in the field ready
# to type the moment it opens.
_PAGE = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
    "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>jobcontext badge</title>"
    "<style>body{font:17px system-ui;margin:0;padding:24px;background:#0b1220;color:#eee}"
    "input{font:17px system-ui;width:100%%;padding:12px;border-radius:8px;border:1px solid #345;"
    "background:#0e1628;color:#eee;box-sizing:border-box}"
    "button{font:17px system-ui;margin-top:12px;padding:12px 20px;border:0;border-radius:8px;"
    "background:#3cc8d2;color:#06202a;font-weight:700}p{color:#8fa}</style>"
    "<h2>jobcontext</h2><form><input name=q autofocus autocapitalize=off "
    "autocomplete=off placeholder='company or role'>"
    "<button>Search on badge</button></form><p>%s</p>"
)


def _as_text(raw):
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode()
        except Exception:  # noqa: BLE001 — binary junk is not a request
            return ""
    return raw or ""


def _query_param(request, name):
    """Pull one parameter out of the request line. MicroPython has no urllib."""
    line = request.split("\r\n", 1)[0]
    if "?" not in line:
        return ""
    path = line.split(" ")[1] if " " in line else line
    if "?" not in path:
        return ""
    for pair in path.split("?", 1)[1].split("&"):
        key, _, value = pair.partition("=")
        if key == name:
            return _unquote(value)[:64]
    return ""


def _unquote(value):
    out = value.replace("+", " ")
    parts = out.split("%")
    if len(parts) == 1:
        return out
    decoded = parts[0]
    for part in parts[1:]:
        try:
            decoded += chr(int(part[:2], 16)) + part[2:]
        except ValueError:  # a stray % that was not an escape
            decoded += "%" + part
    return decoded


def _escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def phone_keyboard_enabled():
    """Is the phone keyboard switched on for this install?

    Off unless something says otherwise, because it opens a listening socket
    and anyone on the network can type into it. badge/install_phone.py writes
    a `features.py` turning it on; badge/install.py deletes that file, so the
    plain installer really is the buttons-only build you fall back to rather
    than the same build with a stale flag left behind.

    secrets.py wins over the generated file, for flipping it without a
    reinstall.
    """
    for mod in (_optional("secrets"), _optional("features")):
        value = getattr(mod, "PHONE_KEYBOARD", None) if mod is not None else None
        if value is not None:
            return bool(value)
    return False


def _optional(name):
    """Import a sibling module if it exists, package-relative or flat.

    Written out rather than computed: a relative __import__ needs globals,
    and the explicit form matches how api.py reaches secrets.py.
    """
    if name == "secrets":
        try:
            from . import secrets  # type: ignore
            return secrets
        except ImportError:
            try:
                import secrets  # type: ignore
                return secrets
            except ImportError:
                return None
    try:
        from . import features  # type: ignore
        return features
    except ImportError:
        try:
            import features  # type: ignore
            return features
        except ImportError:
            return None


def best_available():
    """Return the richest input source this badge can actually offer.

    Ordered by preference, filtered by reality — so a keyboard on the qwiic
    port is used the moment one is plugged in, and the buttons take over the
    moment it is not. BLE stays first in the list so it wins automatically if
    a firmware with bonding ever ships.
    """
    candidates = [BleKeyboardInput(), I2CKeyboardInput()]
    if phone_keyboard_enabled():
        candidates.append(WebInput())
    candidates.append(ButtonInput())
    for source in candidates:
        if source.available():
            return source
    return ButtonInput()
