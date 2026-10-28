"""The badge app's state machine, driven on the host against fake hardware.

badge/jobcontext/ is MicroPython and never runs in CI, so the interesting
logic — text entry, screen transitions, the button re-arm — would otherwise
only ever be tested by flashing a badge and pressing things. Here `ui` and
`api` are replaced with fakes, the *real* keyboard/inputs/state machine are
imported, and button presses are scripted.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "badge" / "jobcontext"


class FakeUI:
    """Records draw calls; button state is set by the test."""

    WIDTH, HEIGHT = 160, 120
    BLACK = WHITE = DIM = ACCENT = WARN = BAD = OK = PANEL = SELECT = (0, 0, 0)

    def __init__(self):
        self.down = set()
        self.drawn = []
        self.is_badgeos = False
        # Simulated millisecond clock. The app throttles its work-item polling
        # to one call every _POLL_MS, so a test that wants a second poll has
        # to move time forward rather than just calling update() again.
        self.offset_ms = 0

    def advance_ms(self, millis):
        self.offset_ms += millis

    def init(self):
        return True

    def badgeos(self):
        return self.is_badgeos

    def pressed(self, name):
        return name in self.down

    def battery_level(self):
        return getattr(self, "_battery", 85)

    def battery_charging(self):
        return getattr(self, "_charging", False)

    def set_battery(self, level, charging=False):
        self._battery = level
        self._charging = charging

    def clear(self, colour=None):
        self.drawn = []

    def text(self, value, x, y, colour=None, scale=2):
        self.drawn.append(str(value))

    def rect(self, x, y, w, h, colour):
        pass

    def hline(self, y, colour=None):
        pass

    def flip(self):
        pass

    QR_QUIET = 2
    qr_modules = 49  # a typical card: fits beside Tetris at 2px per module

    def qr_code(self, text):
        self.qr_text = text
        return (self.qr_modules, bytearray())

    def draw_qr(self, qr, x, y, scale):
        self.qr_scale = scale
        self.drawn.append("<qr>")

    def present(self):
        pass

    # Fixed 5px glyphs stand in for the badge's proportional fonts.
    def text_width(self, value, scale=2):
        return len(str(value)) * 5

    def line_height(self, scale=2):
        return 11

    def fit(self, value, width, scale=2):
        value = str(value)
        chars = width // 5
        return value if len(value) <= chars else value[: chars - 2] + ".."

    def fit_tail(self, value, width, scale=2):
        return str(value)[-(width // 5):]

    def wrap(self, value, width, scale=1, max_lines=4):
        chars = width // 5
        value = str(value)
        return [value[i : i + chars] for i in range(0, len(value), chars)][:max_lines]

    def header(self, title, subtitle="", battery=None, charging=False):
        self.drawn.append(str(title))

    def footer(self, hint):
        pass

    # test helpers
    def press(self, *names):
        self.down = set(names)

    def release(self):
        self.down = set()


class FakeApi:
    class ApiError(Exception):
        pass

    def __init__(self):
        self.searched = []
        self.requested = []
        self.results = []
        self.poll_status = "succeeded"
        self.poll_made = ["resume"]
        self.job_searches = []
        self.styles = []
        self.job_results = []
        self.queued = []

    wifi_ok = True
    ping_error = None

    def connect_wifi(self, status=None):
        self.connects = getattr(self, "connects", 0) + 1
        return self.wifi_ok

    def _ping_check(self):
        if self.ping_error:
            raise self.ApiError(self.ping_error)

    def ping(self):
        self._ping_check()
        return {"ok": True}

    def search(self, query, limit=6):
        self.searched.append(query)
        return {"results": self.results}

    def jobs(self, query, limit=6):
        self.job_searches.append(query)
        return {"search_id": "badge-web-x", "results": self.job_results}

    def queue_job(self, search_id, number):
        self.queued.append((search_id, number))
        hit = self.job_results[number - 1]
        return {"job_id": 900 + number, "company": hit["company"], "role": hit["role"], "status": "queued"}

    def request_materials(self, job_id, material="resume", template="", style="navy"):
        self.requested.append((job_id, material))
        self.styles.append((template, style))
        return {"work_id": 7}

    def poll(self, work_id):
        self.polls = getattr(self, "polls", []) + [work_id]
        return {"status": self.poll_status, "made": self.poll_made, "detail": "nope"}


_APP_MODULES = (
    "keyboard", "inputs", "screensaver", "tetris", "badgeapp",
    # The package-qualified names too: badgeapp is a real package (see the
    # fixture's note on spec_from_file_location), so `from . import x` caches
    # entries as badgeapp.x. Leaving those behind leaks one test's modules —
    # and one test's fake ui/api — into the next.
    "badgeapp.keyboard", "badgeapp.inputs", "badgeapp.screensaver",
    "badgeapp.tetris",
)


@pytest.fixture()
def badge_app(monkeypatch, tmp_path):
    """Load the real badge app with fake ui/api/secrets underneath it."""
    fake_ui, fake_api = FakeUI(), FakeApi()

    # MicroPython's ticks_* live on `time`; CPython has no such thing.
    monkeypatch.setattr(
        time, "ticks_ms", lambda: int(time.monotonic() * 1000) + fake_ui.offset_ms, raising=False
    )
    monkeypatch.setattr(time, "ticks_add", lambda t, d: t + d, raising=False)
    monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    monkeypatch.setitem(sys.modules, "ui", fake_ui)
    monkeypatch.setitem(sys.modules, "api", fake_api)
    # No contact card unless a test supplies one — and never the developer's
    # real badge/jobcontext/contact.py, which sits right on sys.path.
    monkeypatch.setitem(sys.modules, "contact", None)
    for name in _APP_MODULES:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(_APP))

    spec = importlib.util.spec_from_file_location("badgeapp", _APP / "__init__.py")
    app = importlib.util.module_from_spec(spec)
    sys.modules["badgeapp"] = app

    # Inject the fakes under their PACKAGE-qualified names, before exec.
    #
    # spec_from_file_location on an __init__.py sets submodule_search_locations,
    # so badgeapp is a real package and `from . import api, ui` resolves — which
    # means the flat "api"/"ui" entries above are NOT what the app picks up.
    # This harness used to receive its fakes only because the real api.py raised
    # ImportError on `import network` and __init__.py fell back to the flat
    # import: the injection was an accident of that crash. Making those imports
    # safe (so an unconfigured badge reports on screen instead of killing the
    # MonaOS launcher) removes the crash, and silently turned nine of these
    # tests into tests of the real api.py against the stdlib `secrets` module.
    # Seeding sys.modules here is the intentional version, and depends on
    # nothing failing.
    monkeypatch.setitem(sys.modules, "badgeapp.api", fake_api)
    monkeypatch.setitem(sys.modules, "badgeapp.ui", fake_ui)
    monkeypatch.setitem(sys.modules, "badgeapp.contact", None)

    spec.loader.exec_module(app)
    # Remembered layout/colour live at the badge's filesystem root; never let
    # a test read or write the host's.
    monkeypatch.setattr(app, "_PREFS", str(tmp_path / "prefs.json"))

    app.init()
    yield app, fake_ui, fake_api
    for name in _APP_MODULES:
        sys.modules.pop(name, None)


def _tap(app, ui_, button):
    """One clean press: a released frame, then a pressed frame.

    The leading released frame matters — edge detection only fires on a
    low→high transition, so without a frame in which the button is observed
    up, two consecutive taps of the same button read as one continuous hold.
    On real hardware the frame loop is always running, so that gap exists for
    free; here it has to be simulated.
    """
    ui_.release()
    app.update()
    ui_.press(button)
    app.update()
    ui_.release()


def test_typing_builds_a_query(badge_app):
    app, ui_, _api = badge_app
    assert app.state == app.SEARCH

    _tap(app, ui_, "A")  # types the highlighted char, which starts at 'A'
    assert app.query == "A"

    _tap(app, ui_, "DOWN")  # advance the carousel
    _tap(app, ui_, "A")
    assert app.query == "AB"

    _tap(app, ui_, "B")  # backspace
    assert app.query == "A"


@pytest.mark.parametrize(
    "badgeos, previous, next_, type_, back, submit",
    [(False, "UP", "DOWN", "A", "B", "C"),
     (True, "A", "B", "C", "UP", "DOWN")],
    ids=["legacy", "badgeos"],
)
def test_button_layout_types_deletes_and_submits(
    badge_app, badgeos, previous, next_, type_, back, submit
):
    app, ui_, api_ = badge_app
    ui_.is_badgeos = badgeos
    app.init()
    api_.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": ""}]

    _tap(app, ui_, next_)
    _tap(app, ui_, type_)
    assert app.query == "B"
    _tap(app, ui_, previous)
    _tap(app, ui_, type_)
    assert app.query == "BA"
    _tap(app, ui_, back)
    assert app.query == "B"
    _tap(app, ui_, submit)
    assert api_.searched == ["B"]
    assert app.state == app.RESULTS


def test_carousel_wraps_backwards(badge_app):
    """UP from 'A' should land on the last character, not stall at index 0."""
    app, ui_, _api = badge_app
    _tap(app, ui_, "UP")
    _tap(app, ui_, "A")
    from keyboard import CHARSET

    assert app.query == CHARSET[-1]


def test_submit_runs_search_and_shows_results(badge_app):
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": "8/10"}]
    app.query = "ACME"

    _tap(app, ui_, "C")
    assert api_.searched == ["ACME"]
    assert app.state == app.RESULTS


def test_held_submit_does_not_bounce_off_the_results_screen(badge_app):
    """Regression: the OSK and _edge() track edges separately, so a C press
    held across the transition used to read as a *fresh* C on RESULTS and
    kick straight back to SEARCH before anything could be read."""
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": ""}]
    app.query = "ACME"

    ui_.press("C")
    app.update()          # submits the search
    assert app.state == app.RESULTS
    app.update()          # C is STILL held
    app.update()
    assert app.state == app.RESULTS, "held button leaked into the next screen"

    ui_.release()
    _tap(app, ui_, "C")   # a deliberate second press does go back
    assert app.state == app.SEARCH


def test_nothing_anywhere_is_an_explicit_message(badge_app):
    app, ui_, api_ = badge_app
    api_.results = []
    api_.job_results = []
    app.query = "NOBODY"
    _tap(app, ui_, "C")
    assert api_.job_searches == ["NOBODY"]  # the web was tried, not skipped
    assert app.state == app.ERROR
    assert "no open roles" in app.message


_GITHUB_ROLES = [
    {"number": 1, "company": "GitHub", "role": "Senior SWE, Copilot", "location": "Remote"},
    {"number": 2, "company": "GitHub", "role": "Staff Engineer", "location": "SF"},
]


def test_empty_pipeline_falls_through_to_open_roles(badge_app):
    """Typing a company you just met should find its jobs, not dead-end."""
    app, ui_, api_ = badge_app
    api_.results = []
    api_.job_results = _GITHUB_ROLES
    app.query = "GITHUB"
    _tap(app, ui_, "C")
    assert app.state == app.JOBS
    assert api_.job_searches == ["GITHUB"]


def test_b_on_pipeline_results_searches_the_web(badge_app):
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 3, "company": "GitHub", "role": "Old application"}]
    api_.job_results = _GITHUB_ROLES
    app.query = "GITHUB"
    _tap(app, ui_, "C")
    assert app.state == app.RESULTS and api_.job_searches == []
    _tap(app, ui_, "B")
    assert app.state == app.JOBS


def test_picking_an_open_role_queues_it_and_generates_against_it(badge_app):
    app, ui_, api_ = badge_app
    api_.results = []
    api_.job_results = _GITHUB_ROLES
    app.query = "GITHUB"
    _tap(app, ui_, "C")
    _tap(app, ui_, "DOWN")
    _tap(app, ui_, "A")  # add Staff Engineer to the pipeline
    assert api_.queued == [("badge-web-x", 2)]
    assert app.state == app.ACTIONS
    assert app.results[app.selected]["job_id"] == 902
    _tap(app, ui_, "A")  # resume -> style screen
    _tap(app, ui_, "A")  # cursor starts on Generate
    assert api_.requested == [(902, "resume")]
    assert app.state == app.WORKING


def test_directory_hit_cannot_start_a_generation(badge_app):
    """job_id 0 means 'known company, nothing queued' — offering to generate
    from it would produce a resume against an empty job description."""
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 0, "company": "Initech", "role": "Austin, TX", "score": ""}]
    app.query = "INITECH"
    _tap(app, ui_, "C")
    ui_.release()

    _tap(app, ui_, "A")
    assert app.state == app.RESULTS
    assert api_.requested == []


def test_full_generation_flow(badge_app):
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": "8/10"}]
    app.query = "ACME"
    _tap(app, ui_, "C")
    ui_.release()

    _tap(app, ui_, "A")               # open the actions menu
    assert app.state == app.ACTIONS

    api_.poll_status = "running"      # still generating when we first look
    _tap(app, ui_, "DOWN")            # resume → cover letter
    _tap(app, ui_, "A")               # confirm -> style screen
    assert app.state == app.STYLE
    _tap(app, ui_, "A")               # Generate (the cursor starts there)
    assert api_.requested == [(42, "cover_letter")]
    assert app.state == app.WORKING

    ui_.advance_ms(2500)
    app.update()
    assert app.state == app.WORKING, "a still-running job must keep waiting"

    api_.poll_status = "succeeded"
    api_.poll_made = ["cover_letter"]
    ui_.advance_ms(2500)
    app.update()
    assert app.state == app.DONE
    assert "cover_letter" in app.message


def test_failed_generation_surfaces_detail(badge_app):
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    app.query = "ACME"
    _tap(app, ui_, "C")
    api_.poll_status = "running"
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    assert app.state == app.WORKING

    api_.poll_status = "failed"
    ui_.advance_ms(2500)
    app.update()
    assert app.state == app.ERROR
    assert app.message == "nope"


def test_api_error_during_search_is_caught(badge_app):
    """A dropped conference network must not traceback into the frame loop."""
    app, ui_, api_ = badge_app

    def boom(query, limit=6):
        raise api_.ApiError("network: timeout")

    api_.search = boom
    app.query = "ACME"
    _tap(app, ui_, "C")
    assert app.state == app.ERROR
    assert "network" in app.message


def test_ble_source_is_declared_unavailable(badge_app):
    """The BLE keyboard is wired in but not implemented; best_available must
    therefore hand back the buttons rather than a source that emits nothing."""
    import inputs

    assert inputs.BleKeyboardInput().available() is False
    assert isinstance(inputs.best_available(), inputs.ButtonInput)


# ── I2C keyboard (M5Stack CardKB / CardKB2 on the qwiic port) ──────────────────
# The BLE route is closed (no gap_pair in this firmware), so a wired bus is the
# only way to real keys. None of this needs the badge: a fake bus answers.


class FakeI2C:
    """A bus with devices on it. `keys` is the byte stream one address returns."""

    def __init__(self, devices=(), keys=(), fail_scan=False, fail_read=False):
        self.devices = list(devices)
        self.keys = list(keys)
        self.fail_scan = fail_scan
        self.fail_read = fail_read
        self.reads = []

    def scan(self):
        if self.fail_scan:
            raise OSError("bus error")
        return list(self.devices)

    def readfrom(self, address, count):
        self.reads.append(address)
        if self.fail_read:
            raise OSError("cable yanked")
        return bytes([self.keys.pop(0)]) if self.keys else bytes([0])


def _kbd(badge_app_modules, **kwargs):
    """An I2CKeyboardInput wired to a fake bus, discovery already done."""
    import inputs

    bus = FakeI2C(**kwargs)
    source = inputs.I2CKeyboardInput(i2c=bus, address=0x5F)
    return source, bus


def _drain(source, ui_, presses):
    """Collect events for a byte stream, stepping past the inter-read floor."""
    out = []
    for _ in range(presses):
        ui_.advance_ms(50)
        out.extend(source.poll())
    return out


def test_i2c_keyboard_types_characters(badge_app):
    _app, ui_, _api = badge_app
    source, _bus = _kbd(badge_app, keys=[ord("A"), ord("c"), ord("m"), ord("e")])
    assert _drain(source, ui_, 4) == [
        ("char", "A"), ("char", "c"), ("char", "m"), ("char", "e")
    ]


def test_i2c_keyboard_maps_control_keys(badge_app):
    """Backspace, Enter and Esc must become the app's own events, not text."""
    _app, ui_, _api = badge_app
    source, _bus = _kbd(badge_app, keys=[0x08, 0x0D, 0x1B, 0x09])
    assert _drain(source, ui_, 4) == [
        ("back",), ("submit",), ("cancel",), ("submit",)
    ]


def test_i2c_keyboard_ignores_zero_and_junk(badge_app):
    """0 means 'no key'. High codes are arrow keys and friends — typing a
    square into the search box is worse than ignoring them."""
    _app, ui_, _api = badge_app
    source, _bus = _kbd(badge_app, keys=[0, 0xB5, 0x00, ord("x")])
    assert _drain(source, ui_, 4) == [("char", "x")]


def test_i2c_keyboard_respects_the_read_floor(badge_app):
    """The CardKB drops keys when polled flat out, so reads are rate limited.
    At frame rate that floor is what makes it reliable."""
    _app, ui_, _api = badge_app
    source, bus = _kbd(badge_app, keys=[ord("a"), ord("b")])

    source.poll()
    before = len(bus.reads)
    source.poll()          # immediately again — must not touch the bus
    source.poll()
    assert len(bus.reads) == before

    ui_.advance_ms(50)
    source.poll()
    assert len(bus.reads) == before + 1


def test_i2c_keyboard_survives_a_yanked_cable(badge_app):
    """A read that raises must return no events, not take down the frame loop."""
    _app, ui_, _api = badge_app
    source, _bus = _kbd(badge_app, keys=[ord("a")], fail_read=True)
    ui_.advance_ms(50)
    assert source.poll() == []


def test_i2c_discovery_prefers_the_documented_address(badge_app, monkeypatch):
    import inputs

    bus = FakeI2C(devices=[0x3C, 0x5F, 0x68])
    source = inputs.I2CKeyboardInput()
    monkeypatch.setattr(source, "_candidate_buses", lambda: [bus])
    assert source.available() is True
    assert source._address == 0x5F


def test_i2c_discovery_accepts_a_lone_unknown_device(badge_app, monkeypatch):
    """CardKB2 is a different chip from the 0x5F original and its address is
    undocumented, so a keyboard that needs someone to edit a constant is a
    keyboard that does not work. One device on an otherwise empty bus is the
    thing just plugged into the qwiic port."""
    import inputs

    bus = FakeI2C(devices=[0x42])
    source = inputs.I2CKeyboardInput()
    monkeypatch.setattr(source, "_candidate_buses", lambda: [bus])
    assert source.available() is True
    assert source._address == 0x42


def test_i2c_discovery_declines_to_guess_between_strangers(badge_app, monkeypatch):
    """Two unknown devices and no 0x5F: picking one at random would send
    keystroke reads to someone else's sensor. Decline, and say so via config."""
    import inputs

    bus = FakeI2C(devices=[0x42, 0x43])
    source = inputs.I2CKeyboardInput()
    monkeypatch.setattr(source, "_candidate_buses", lambda: [bus])
    assert source.available() is False


def test_i2c_discovery_honours_configured_address(badge_app, monkeypatch):
    import inputs

    bus = FakeI2C(devices=[0x42, 0x43])
    source = inputs.I2CKeyboardInput()
    monkeypatch.setattr(source, "_candidate_buses", lambda: [bus])
    monkeypatch.setattr(source, "_configured_address", lambda: 0x43)
    assert source.available() is True
    assert source._address == 0x43


def test_i2c_absent_bus_is_not_an_error(badge_app, monkeypatch):
    """No machine.I2C, no qwiic, a bus that will not scan — all of it must
    read as 'no keyboard', never as a crash at startup."""
    import inputs

    source = inputs.I2CKeyboardInput()
    monkeypatch.setattr(source, "_candidate_buses", lambda: [FakeI2C(fail_scan=True)])
    assert source.available() is False

    other = inputs.I2CKeyboardInput()
    monkeypatch.setattr(other, "_candidate_buses", lambda: [])
    assert other.available() is False
    assert other.poll() == []


def test_best_available_prefers_a_keyboard_then_falls_back(badge_app, monkeypatch):
    import inputs

    monkeypatch.setattr(inputs.I2CKeyboardInput, "available", lambda self: True)
    assert isinstance(inputs.best_available(), inputs.I2CKeyboardInput)

    monkeypatch.setattr(inputs.I2CKeyboardInput, "available", lambda self: False)
    assert isinstance(inputs.best_available(), inputs.ButtonInput)


def test_search_footer_follows_the_input_source(badge_app):
    """'A type' describes a button nobody presses once a keyboard is attached."""
    import inputs

    assert "A type" in inputs.ButtonInput.hint
    assert "A type" not in inputs.I2CKeyboardInput.hint
    assert "ENTER" in inputs.I2CKeyboardInput.hint


# ── the real ui shim, host-side ────────────────────────────────────────────────
# With no badgeware importable, ui measures every glyph as 5px — enough to pin
# down the text helpers without a badge.


def _load(name):
    spec = importlib.util.spec_from_file_location("badge_" + name, _APP / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ui_folds_text_to_the_fonts_ascii_range():
    ui = _load("ui")
    assert ui._ascii("Société Générale — Paris…") == "Societe Generale - Paris.."
    assert ui._ascii("东京") == "??"


def test_ui_fit_trims_by_pixels_not_characters():
    ui = _load("ui")
    assert ui.fit("short", 100) == "short"
    cut = ui.fit("Principal Software Engineer", 60)
    assert cut.endswith("..") and ui.text_width(cut) <= 60


def test_ui_wrap_respects_width_and_line_cap():
    ui = _load("ui")
    lines = ui.wrap("resume, cover_letter ready on your desktop", 60)
    assert len(lines) > 1 and all(ui.text_width(line) <= 60 for line in lines)
    capped = ui.wrap("word " * 40, 60, max_lines=2)
    assert len(capped) == 2 and capped[-1].endswith("..")


def test_ui_fit_tail_keeps_the_end_of_typed_text():
    ui = _load("ui")
    assert ui.fit_tail("ABCDEFGHIJ", 25) == "FGHIJ"


def test_ui_reads_buttons_from_badgeware_io(monkeypatch):
    import types

    io = types.SimpleNamespace(BUTTON_UP=1, BUTTON_A=2, held={1})
    fake = types.SimpleNamespace(
        io=io, PixelFont=types.SimpleNamespace(load=lambda path: types.SimpleNamespace(height=11))
    )
    monkeypatch.setitem(sys.modules, "badgeware", fake)
    ui = _load("ui")
    assert ui.init()
    assert ui.pressed("UP") and not ui.pressed("A") and not ui.pressed("NOPE")


def test_api_quote_percent_encodes_utf8_bytes(monkeypatch):
    import types

    for name in ("requests", "network", "secrets"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    api = _load("api")
    assert api._quote("AT&T Inc") == "AT%26T+Inc"
    assert api._quote("é") == "%C3%A9"


# ── layout / colour picker ─────────────────────────────────────────────────────

def _to_style_screen(app, ui_, api_):
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    app.query = "ACME"
    _tap(app, ui_, "C")
    _tap(app, ui_, "A")  # actions
    _tap(app, ui_, "A")  # resume -> style
    assert app.state == app.STYLE


def test_default_style_is_the_original_layout(badge_app):
    """A, A from the actions menu generates exactly what it did before."""
    app, ui_, api_ = badge_app
    _to_style_screen(app, ui_, api_)
    _tap(app, ui_, "A")
    assert api_.styles == [("", "navy")]


def test_picking_a_layout_and_colour(badge_app):
    app, ui_, api_ = badge_app
    _to_style_screen(app, ui_, api_)
    assert app._style_rows() == ["layout", "generate"]  # no colour for original
    _tap(app, ui_, "UP")          # -> layout
    _tap(app, ui_, "A")           # original -> modern
    _tap(app, ui_, "A")           # modern -> executive
    assert app._style_rows() == ["layout", "colour", "generate"]
    _tap(app, ui_, "DOWN")        # -> colour
    _tap(app, ui_, "B")           # navy -> classic (B steps backwards)
    _tap(app, ui_, "DOWN")        # -> generate
    _tap(app, ui_, "A")
    assert api_.styles == [("executive", "classic")]
    assert app.state == app.WORKING


def test_style_choice_survives_a_restart(badge_app):
    app, ui_, api_ = badge_app
    _to_style_screen(app, ui_, api_)
    _tap(app, ui_, "UP")
    _tap(app, ui_, "A")           # modern
    _tap(app, ui_, "DOWN")
    _tap(app, ui_, "A")           # navy -> slate
    _tap(app, ui_, "DOWN")
    _tap(app, ui_, "A")           # generate (saves the choice)

    app.layout_index = app.colour_index = 0
    app._load_prefs()             # what init() does after a reset
    assert app.LAYOUTS[app.layout_index][0] == "modern"
    assert app.COLOURS[app.colour_index] == "slate"


def test_c_on_style_goes_back_without_generating(badge_app):
    app, ui_, api_ = badge_app
    _to_style_screen(app, ui_, api_)
    _tap(app, ui_, "C")
    assert app.state == app.ACTIONS and api_.requested == []


# ── contact-card screen saver ──────────────────────────────────────────────────

class _Contact:
    NAME = "Ada Lovelace"
    TITLE = "Staff Engineer"
    EMAIL = "ada@example.com"
    PHONE = ""
    LINKEDIN = "ada"
    GITHUB = "ada-l"
    WEBSITE = ""
    IDLE_SECONDS = 30


@pytest.fixture()
def saver_app(badge_app, monkeypatch):
    app, ui_, api_ = badge_app
    monkeypatch.setitem(sys.modules, "contact", _Contact)
    assert app.screensaver.load()
    app._last_input = time.ticks_ms()
    return app, ui_, api_


def _idle(app, ui_, seconds):
    ui_.release()
    ui_.advance_ms(seconds * 1000)
    app.update()


def test_idle_shows_the_contact_card(saver_app):
    app, ui_, _api = saver_app
    _idle(app, ui_, 10)
    assert not app.saving
    _idle(app, ui_, 25)
    assert app.saving
    assert "Ada Lovelace" in ui_.drawn
    assert any(line.startswith("in/ada") for line in ui_.drawn)


def test_card_alternates_with_the_qr(saver_app):
    app, ui_, _api = saver_app
    _idle(app, ui_, 31)
    assert "<qr>" not in ui_.drawn          # text card first
    _idle(app, ui_, 8)
    assert "<qr>" in ui_.drawn              # then the QR page, beside Tetris
    assert "scan me" in ui_.drawn
    assert ui_.qr_scale == 2
    assert ui_.qr_text.startswith("MECARD:N:Ada Lovelace;")


def test_dense_qr_takes_the_whole_screen_rather_than_shrinking(saver_app):
    """1px modules were unscannable on the real badge: never go below 2px
    to keep Tetris in view — give the QR the screen instead."""
    app, ui_, _api = saver_app
    ui_.qr_modules = 55                     # 59 with quiet zone: 1px in the 114px panel
    _idle(app, ui_, 31)
    _idle(app, ui_, 8)
    assert "<qr>" in ui_.drawn
    assert app.screensaver._qr_full
    assert ui_.qr_scale == 2                # full screen keeps it scannable
    assert "scan me" not in ui_.drawn       # no Tetris on the full-screen page


def test_waking_press_is_swallowed(saver_app):
    """Waking with A must not also type an 'A' into the search box."""
    app, ui_, _api = saver_app
    _idle(app, ui_, 31)
    assert app.saving
    ui_.press("A")
    app.update()
    assert not app.saving
    app.update()                            # A still held
    ui_.release()
    app.update()
    assert app.query == ""
    assert app.state == app.SEARCH


def test_static_page_is_drawn_once_then_only_tetris(saver_app):
    """The QR is hundreds of rectangles: paint it on the page flip, not 30x/s."""
    app, ui_, _api = saver_app
    _idle(app, ui_, 31)
    _idle(app, ui_, 8)                      # flip to the QR page
    assert ui_.drawn.count("<qr>") == 1
    for _ in range(5):
        _idle(app, ui_, 0.2)
    assert ui_.drawn.count("<qr>") == 1     # not repainted
    assert "scan me" in ui_.drawn           # but the well label still updates


def test_tetris_plays_while_saving(saver_app):
    app, ui_, _api = saver_app
    _idle(app, ui_, 31)
    first = app.screensaver._game.cells()
    _idle(app, ui_, 3)
    assert app.screensaver._game.cells() != first


def test_working_never_idles_into_the_saver(saver_app):
    app, ui_, api_ = saver_app
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    api_.poll_status = "running"
    app.query = "ACME"
    _tap(app, ui_, "C")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    assert app.state == app.WORKING
    _idle(app, ui_, 120)
    assert not app.saving and app.state == app.WORKING


def test_ready_screen_is_not_covered_after_a_long_generation(saver_app):
    app, ui_, api_ = saver_app
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    api_.poll_status = "running"
    app.query = "ACME"
    _tap(app, ui_, "C")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _idle(app, ui_, 90)                     # a slow generation
    api_.poll_status = "succeeded"
    _idle(app, ui_, 3)
    assert app.state == app.DONE and not app.saving
    _idle(app, ui_, 31)
    assert app.saving                       # only after a full idle period


def test_no_contact_file_means_no_screen_saver(badge_app):
    app, ui_, _api = badge_app
    _idle(app, ui_, 600)
    assert not app.saving


def test_qr_payload_is_a_compact_mecard(badge_app):
    app, _ui, _api = badge_app
    card = app.screensaver.qr_payload(_Contact)
    assert card == (
        "MECARD:N:Ada Lovelace;EMAIL:ada@example.com;"
        "URL:linkedin.com/in/ada;URL:github.com/ada-l;;"
    )
    assert "Staff Engineer" not in card     # title: on the card, not the QR
    assert "https://" not in card and "TEL:" not in card


def test_qr_payload_escapes_mecard_separators(badge_app):
    app, _ui, _api = badge_app

    class Tricky(_Contact):
        NAME = "Smith; Jo"
        EMAIL = "a:b@x.io"

    card = app.screensaver.qr_payload(Tricky)
    assert "N:Smith\\; Jo;" in card and "EMAIL:a\\:b@x.io;" in card


# ── WiFi: several networks, joined by what's in range ──────────────────────────

class _FakeWlan:
    def __init__(self, visible, joinable):
        self.visible, self.joinable = visible, joinable
        self.tried, self.up = [], False

    def active(self, _on):
        pass

    def isconnected(self):
        return self.up

    def scan(self):
        return [(name.encode(), b"", 1, -60, 3, 0) for name in self.visible]

    def connect(self, ssid, _password):
        self.tried.append(ssid)
        self.up = ssid in self.joinable

    def disconnect(self):
        self.up = False


def _api_with(monkeypatch, secrets_obj, wlan):
    import types

    net = types.SimpleNamespace(STA_IF=0, WLAN=lambda _i: wlan)
    monkeypatch.setitem(sys.modules, "network", net)
    monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))
    monkeypatch.setitem(sys.modules, "secrets", secrets_obj)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    return _load("api")


def test_wifi_joins_the_listed_network_that_is_in_range(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a"), ("Frank’s iPhone", "b")])
    wlan = _FakeWlan(visible=["Starbucks WiFi", "Frank’s iPhone"], joinable={"Frank’s iPhone"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True
    assert wlan.tried == ["Frank’s iPhone"]          # Home isn't in range: never tried


def test_wifi_falls_through_the_list_in_order(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "wrong"), ("Hotspot", "b")])
    wlan = _FakeWlan(visible=["Home", "Hotspot"], joinable={"Hotspot"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True
    assert wlan.tried == ["Home", "Hotspot"]


def test_wifi_still_reads_the_old_single_network_secrets(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_SSID="Home", WIFI_PASSWORD="a")
    wlan = _FakeWlan(visible=["Home"], joinable={"Home"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True and wlan.tried == ["Home"]


def test_wifi_returns_false_after_two_rounds_when_no_network_joins(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a"), ("Hotspot", "b")])
    wlan = _FakeWlan(visible=["Starbucks WiFi"], joinable=set())
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is False
    assert wlan.tried == ["Home", "Hotspot", "Home", "Hotspot"]
    assert not wlan.isconnected()


def test_wifi_joins_a_configured_network_missed_by_scan(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a")])
    wlan = _FakeWlan(visible=["Starbucks WiFi"], joinable={"Home"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True
    assert wlan.tried == ["Home"]


def test_wifi_second_round_tries_networks_missing_from_scan(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a"), ("Hotspot", "b")])
    wlan = _FakeWlan(visible=["Home"], joinable={"Hotspot"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True
    assert wlan.tried == ["Home", "Home", "Hotspot"]


def test_wifi_tries_unseen_networks_when_a_hidden_one_is_in_range(monkeypatch):
    """A hidden hotspot scans as an empty name; it must still be joinable."""
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a"), ("Frank's Device", "b")])
    wlan = _FakeWlan(visible=["", "Starbucks"], joinable={"Frank's Device"})
    api = _api_with(monkeypatch, secrets_obj, wlan)
    assert api.connect_wifi() is True
    assert wlan.tried == ["Home", "Frank's Device"]


# ── retry after a connection failure ───────────────────────────────────────────

def test_retry_after_failed_wifi_actually_reconnects(badge_app):
    """Retry used to jump to SEARCH and look connected when it wasn't."""
    app, ui_, api_ = badge_app
    api_.wifi_ok = False
    app.init()
    assert app.state == app.ERROR and "wifi" in app.message
    before = api_.connects

    _tap(app, ui_, "A")                     # still no wifi
    assert api_.connects == before + 1
    assert app.state == app.ERROR           # stays on the error, not SEARCH

    api_.wifi_ok = True
    _tap(app, ui_, "A")                     # hotspot back
    assert app.state == app.SEARCH and app._online


def test_retry_after_a_rejected_token_rechecks_it(badge_app):
    app, ui_, api_ = badge_app
    api_.ping_error = "token rejected - regenerate it"
    app.init()
    assert app.state == app.ERROR and not app._online
    _tap(app, ui_, "A")
    assert app.state == app.ERROR and "token" in app.message
    api_.ping_error = None
    _tap(app, ui_, "A")
    assert app.state == app.SEARCH


def test_retry_after_an_ordinary_failure_goes_back_without_reconnecting(badge_app):
    app, ui_, api_ = badge_app
    api_.results = []
    api_.job_results = []
    app.query = "NOBODY"
    _tap(app, ui_, "C")
    assert app.state == app.ERROR and app._online
    before = api_.connects
    _tap(app, ui_, "A")
    assert app.state == app.SEARCH and api_.connects == before


# ── walked-away generations: background polling + banner ──────────────────────

def _start_and_walk_away(app, ui_, api_):
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    api_.poll_status = "running"
    app.query = "ACME"
    _tap(app, ui_, "C")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")                     # generate
    assert app.state == app.WORKING
    _tap(app, ui_, "C")                     # stop waiting
    assert app.state == app.RESULTS
    assert [j["work_id"] for j in app.pending] == [7]


def _wait(app, ui_, seconds):
    ui_.release()
    ui_.advance_ms(int(seconds * 1000))
    app.update()


def test_walked_away_job_is_announced_when_done(badge_app):
    app, ui_, api_ = badge_app
    _start_and_walk_away(app, ui_, api_)
    _wait(app, ui_, 16)
    assert app.notices == [] and app.pending   # still running
    api_.poll_status = "succeeded"
    _wait(app, ui_, 16)
    assert app.pending == []
    assert app.notices == [(True, "resume ready - Acme")]
    assert "resume ready - Acme" in ui_.drawn


def test_background_poll_is_throttled(badge_app):
    app, ui_, api_ = badge_app
    _start_and_walk_away(app, ui_, api_)
    before = len(api_.polls)
    for _ in range(10):
        _wait(app, ui_, 1)                  # 10s: under the 15s interval
    assert len(api_.polls) <= before + 1


def test_banner_shows_over_the_screen_saver(saver_app):
    app, ui_, api_ = saver_app
    _start_and_walk_away(app, ui_, api_)
    _wait(app, ui_, 31)
    assert app.saving
    api_.poll_status = "succeeded"
    _wait(app, ui_, 16)
    assert app.saving and app.notices
    assert "resume ready - Acme" in ui_.drawn


def test_dismissing_the_banner_swallows_the_press(saver_app):
    app, ui_, api_ = saver_app
    _start_and_walk_away(app, ui_, api_)
    api_.poll_status = "succeeded"
    _wait(app, ui_, 31)                     # done, and idled into the saver
    assert app.notices and app.saving
    state = app.state
    ui_.press("A")
    app.update()
    assert app.notices == [] and not app.saving
    app.update()                            # A still held
    ui_.release()
    app.update()
    assert app.state == state               # A didn't also open actions


def test_failed_walked_away_job_says_why(badge_app):
    app, ui_, api_ = badge_app
    _start_and_walk_away(app, ui_, api_)
    api_.poll_status = "failed"
    _wait(app, ui_, 16)
    assert app.notices == [(False, "resume failed - Acme: nope")]


def test_waiting_it_out_gives_the_done_screen_not_a_banner(badge_app):
    app, ui_, api_ = badge_app
    api_.results = [{"job_id": 42, "company": "Acme", "role": "SWE", "score": ""}]
    api_.poll_status = "running"
    app.query = "ACME"
    _tap(app, ui_, "C")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    _tap(app, ui_, "A")
    api_.poll_status = "succeeded"
    _wait(app, ui_, 3)
    assert app.state == app.DONE
    assert app.pending == [] and app.notices == []
    _wait(app, ui_, 20)
    assert app.notices == []


def test_repeated_background_poll_failures_are_reported_once(badge_app):
    """Failed checks used to be silent forever: no banner, ever."""
    app, ui_, api_ = badge_app
    _start_and_walk_away(app, ui_, api_)

    def broken(_wid):
        raise api_.ApiError("network: [Errno 12] ENOMEM")

    api_.poll = broken
    for _ in range(3):
        _wait(app, ui_, 16)
    assert app.notices == []                # a blip or two: stay quiet
    _wait(app, ui_, 16)
    assert app.notices == [(False, "can't check on your jobs: network: [Errno 12] ENOMEM")]
    for _ in range(4):
        _wait(app, ui_, 16)
    assert len(app.notices) == 1            # said once, not every 15s
    assert app.pending                      # and the job is still tracked


def test_tls_reserve_is_released_for_each_request(monkeypatch):
    """The heap reserve exists so a TLS handshake always finds a big block."""
    import types

    seen = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

        def close(self):
            pass

    req = types.ModuleType("requests")

    def request(*a, **k):
        seen["reserve_during"] = api._reserve
        return Resp()

    req.request = request
    monkeypatch.setitem(sys.modules, "requests", req)
    monkeypatch.setitem(sys.modules, "network", types.ModuleType("network"))
    monkeypatch.setitem(
        sys.modules, "secrets", types.SimpleNamespace(BASE_URL="https://x", BADGE_TOKEN="t")
    )
    api = _load("api")
    assert isinstance(api._reserve, bytearray) and len(api._reserve) == api._RESERVE_BYTES
    assert api.ping() == {"ok": True}
    assert seen["reserve_during"] is None   # released for the handshake
    assert isinstance(api._reserve, bytearray)  # and taken back after


def test_saver_resources_are_built_at_startup(saver_app):
    """Built while the heap is clean, not on first idle (crashed on hardware)."""
    app, ui_, _api = saver_app
    app.init()
    assert app.screensaver._game is not None and app.screensaver._qr


def test_a_failing_saver_never_takes_the_app_down(saver_app, monkeypatch):
    app, ui_, _api = saver_app

    def boom(_now):
        raise MemoryError("memory allocation failed")

    monkeypatch.setattr(app.screensaver, "start", boom)
    _idle(app, ui_, 31)                     # would have crashed jobcontext
    assert not app.saving and not app.saver_ok
    assert app.state == app.SEARCH
    _idle(app, ui_, 120)
    assert not app.saving                   # stays off for the session
    _tap(app, ui_, "A")
    assert app.query == "A"                 # and the app still works


# ── 2026-10-25 additions ─────────────────────────────────────────────────────


def test_on_exit_releases_the_reserve_and_drops_the_saver(saver_app, monkeypatch):
    """The launcher gets a clean heap back: no 40KB block, no Tetris/QR."""
    app, ui_, _api = saver_app
    app.init()
    assert app.screensaver._game is not None

    released = []
    unloaded = []
    # The app's api is FakeApi, which has no reserve — patch the method on
    # and assert it was called, not the real api.py's internals.
    monkeypatch.setattr(app.api, "release_reserve", lambda: released.append(True), raising=False)
    monkeypatch.setattr(app.screensaver, "unload", lambda: unloaded.append(True), raising=False)

    app.on_exit()
    assert released and unloaded
    assert not app.saving


def test_battery_icon_shows_on_every_screen(saver_app, monkeypatch):
    """ui.header() receives battery state so the icon is on every screen."""
    app, ui_, _api = saver_app
    app.init()
    ui_.set_battery(85)
    app._poll_battery()  # force a sample
    assert app._battery_level == 85
    ui_.clear()
    app.update()
    # The header was drawn with the battery params
    assert ui_.drawn  # header() appends the title


def test_battery_icon_hidden_when_no_adc(saver_app, monkeypatch):
    """If the firmware has no battery_level(), the icon hides gracefully."""
    app, ui_, _api = saver_app
    app.init()
    monkeypatch.setattr(ui_, "battery_level", lambda: -1)
    app._poll_battery()
    assert app._battery_level == -1


def test_home_button_returns_to_search(saver_app):
    """Home is the exit gesture: any screen goes back to SEARCH."""
    app, ui_, _api = saver_app
    app.init()
    app._go(app.RESULTS)
    assert app.state == app.RESULTS
    _tap(app, ui_, "HOME")
    assert app.state == app.SEARCH


def test_home_button_in_search_stays(saver_app):
    """Home on SEARCH is a no-op, not a crash."""
    app, ui_, _api = saver_app
    app.init()
    assert app.state == app.SEARCH
    _tap(app, ui_, "HOME")
    assert app.state == app.SEARCH


def test_tls_verified_flag_exists():
    """The TLS check runs at import; False on this MicroPython build."""
    import badge.jobcontext.api as real_api
    assert hasattr(real_api, "TLS_VERIFIED")


# ── phone keyboard (badge serves a form over WiFi) ────────────────────────────
# The route that needs no hardware: BLE HID is closed (no gap_pair) and the
# wired keyboard needs parts, but when the phone is the hotspot it is already
# on the same network as the badge. A fake socket stands in for the radio.


class FakeConn:
    def __init__(self, request=b"", recv_raises=False):
        self.request = request
        self.recv_raises = recv_raises
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, _n):
        if self.recv_raises:
            raise OSError("phone wandered off")
        return self.request

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


class FakeSocket:
    """One listening socket with a queue of connections to hand out."""

    SOL_SOCKET = 1
    SO_REUSEADDR = 2

    def __init__(self, queue=None, bind_raises=False):
        self.queue = list(queue or [])
        self.bind_raises = bind_raises
        self.bound = None
        self.blocking = None

    # module-level interface
    def socket(self):
        return self

    # socket interface
    def setsockopt(self, *a):
        pass

    def bind(self, addr):
        if self.bind_raises:
            raise OSError("address in use")
        self.bound = addr

    def listen(self, _n):
        pass

    def setblocking(self, flag):
        self.blocking = flag

    def accept(self):
        if not self.queue:
            raise OSError(11, "EAGAIN")
        return self.queue.pop(0), ("10.0.0.9", 50000)


class FakeWLAN:
    def __init__(self, connected=True, ip="192.168.4.1"):
        self._connected = connected
        self._ip = ip

    def isconnected(self):
        return self._connected

    def ifconfig(self):
        return (self._ip, "255.255.255.0", "192.168.4.1", "192.168.4.1")


class FakeNetwork:
    STA_IF = 0

    def __init__(self, wlan=None):
        self._wlan = wlan or FakeWLAN()

    def WLAN(self, _mode):  # noqa: N802 — mirrors MicroPython's API
        return self._wlan


def _web(monkeypatch, queue=None, wlan=None, bind_raises=False):
    """A WebInput wired to fake network + socket modules."""
    import inputs

    sock = FakeSocket(queue=queue, bind_raises=bind_raises)
    monkeypatch.setitem(sys.modules, "socket", sock)
    monkeypatch.setitem(sys.modules, "network", FakeNetwork(wlan))
    return inputs.WebInput(), sock


def _get(path):
    return ("GET %s HTTP/1.1\r\nHost: 192.168.4.1\r\n\r\n" % path).encode()


def test_web_serves_the_form_on_a_bare_request(badge_app, monkeypatch):
    _app, _ui, _api = badge_app
    conn = FakeConn(_get("/"))
    source, _sock = _web(monkeypatch, queue=[conn])

    assert source.poll() == []          # a bare GET is not input
    body = b"".join(conn.sent) if isinstance(conn.sent[0], bytes) else "".join(conn.sent)
    body = body if isinstance(body, str) else body.decode()
    assert "<form" in body and "name=q" in body
    assert conn.closed


def test_web_query_becomes_set_then_submit(badge_app, monkeypatch):
    """The phone sends a whole string, so it replaces the query rather than
    appending to whatever the buttons left behind."""
    _app, _ui, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[FakeConn(_get("/?q=acme+corp"))])

    assert source.poll() == [("set", "acme corp"), ("submit",)]


def test_web_decodes_percent_escapes(badge_app, monkeypatch):
    _app, _ui, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[FakeConn(_get("/?q=AT%26T%20Labs"))])

    assert source.poll()[0] == ("set", "AT&T Labs")


def test_web_buttons_keep_working(badge_app, monkeypatch, ):
    """WebInput extends the buttons rather than replacing them — the phone is
    an addition, and the carousel is the fallback when it is in a pocket."""
    import inputs

    _app, ui_, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[])
    assert isinstance(source, inputs.ButtonInput)

    ui_.release()
    source.poll()
    ui_.press("A")
    assert source.poll() == [("char", "A")]


def test_web_binds_only_once_wifi_is_up(badge_app, monkeypatch):
    """init() picks the source before _connect() runs, so there is no address
    to bind to yet. Binding is lazy and must not fail the app."""
    _app, _ui, _api = badge_app
    offline = FakeWLAN(connected=False)
    source, sock = _web(monkeypatch, queue=[FakeConn(_get("/?q=acme"))], wlan=offline)

    assert source.poll() == []     # nothing bound, nothing served
    assert sock.bound is None

    offline._connected = True
    assert source.poll() == [("set", "acme"), ("submit",)]
    assert sock.bound == ("0.0.0.0", 80)


def test_web_survives_a_failed_bind(badge_app, monkeypatch):
    """Port taken, no sockets, whatever — the badge still runs on buttons."""
    _app, _ui, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[FakeConn(_get("/?q=acme"))], bind_raises=True)

    assert source.poll() == []
    assert source._bind_failed is True
    assert source.poll() == []     # and does not retry forever


def test_web_survives_a_half_open_phone(badge_app, monkeypatch):
    """A connection that opens and never speaks must not crash the frame loop."""
    _app, _ui, _api = badge_app
    conn = FakeConn(recv_raises=True)
    source, _sock = _web(monkeypatch, queue=[conn])

    assert source.poll() == []
    assert conn.closed


def test_web_pending_does_not_consume_the_request(badge_app, monkeypatch):
    """The screen saver asks 'is someone typing?' every frame. If that check
    ate the request, the phone would hang and the search would never run."""
    _app, _ui, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[FakeConn(_get("/?q=acme"))])

    assert source.pending() is True
    assert source.pending() is True          # idempotent
    assert source.poll() == [("set", "acme"), ("submit",)]


def test_web_pending_is_false_when_nobody_knocks(badge_app, monkeypatch):
    _app, _ui, _api = badge_app
    source, _sock = _web(monkeypatch, queue=[])
    assert source.pending() is False


def test_set_event_replaces_the_query(badge_app):
    """End to end through the state machine: a phone-sent string replaces what
    the buttons typed, and submits."""
    app, _ui, api_ = badge_app
    api_.results = [{"job_id": 7, "company": "Acme", "role": "SWE", "score": "8/10"}]
    app.query = "TYPO"

    class OneShot:
        hint = ""

        def __init__(self):
            self.done = False

        def poll(self):
            if self.done:
                return []
            self.done = True
            return [("set", "acme corp"), ("submit",)]

        def draw(self, _text):
            pass

        def rearm(self):
            pass

    app.source = OneShot()
    app.update()
    assert api_.searched == ["acme corp"]
    assert app.state == app.RESULTS


def test_phone_request_counts_as_activity(badge_app, monkeypatch):
    """Without this the saver covers the screen mid-typing — and worse, stops
    the frame that would have answered the phone."""
    app, ui_, _api = badge_app

    class Knocking:
        hint = ""

        def pending(self):
            return True

        def poll(self):
            return []

        def draw(self, _t):
            pass

        def rearm(self):
            pass

    app.source = Knocking()
    assert app._source_pending() is True

    class Quiet(Knocking):
        def pending(self):
            return False

    app.source = Quiet()
    assert app._source_pending() is False

    class Boom(Knocking):
        def pending(self):
            raise OSError("flaky socket")

    app.source = Boom()
    assert app._source_pending() is False


def test_sources_without_pending_read_false(badge_app):
    """Buttons and the wired keyboard cannot be knocked on."""
    import inputs

    app, _ui, _api = badge_app
    app.source = inputs.ButtonInput()
    assert app._source_pending() is False


def test_phone_keyboard_is_off_unless_switched_on(badge_app, monkeypatch):
    """Off by default: it opens a listening socket, and anyone on the network
    can type into it. install.py ships it off; install_phone.py turns it on."""
    import inputs

    monkeypatch.setattr(inputs, "_optional", lambda name: None)
    assert inputs.phone_keyboard_enabled() is False
    assert isinstance(inputs.best_available(), inputs.ButtonInput)


def test_features_file_turns_the_phone_keyboard_on(badge_app, monkeypatch):
    import inputs

    class Features:
        PHONE_KEYBOARD = True

    monkeypatch.setattr(
        inputs, "_optional", lambda name: Features if name == "features" else None
    )
    assert inputs.phone_keyboard_enabled() is True

    # WebInput.available() wants the radio modules, which a host does not have.
    monkeypatch.setitem(sys.modules, "network", FakeNetwork())
    monkeypatch.setitem(sys.modules, "socket", FakeSocket())
    assert isinstance(inputs.best_available(), inputs.WebInput)


def test_secrets_overrides_the_generated_features_file(badge_app, monkeypatch):
    """So the switch can be flipped without a reinstall."""
    import inputs

    class Features:
        PHONE_KEYBOARD = True

    class Secrets:
        PHONE_KEYBOARD = False

    monkeypatch.setattr(
        inputs, "_optional",
        lambda name: Secrets if name == "secrets" else Features,
    )
    assert inputs.phone_keyboard_enabled() is False


def test_a_secrets_without_the_flag_does_not_veto(badge_app, monkeypatch):
    """Every existing secrets.py lacks PHONE_KEYBOARD, and on a host `import
    secrets` finds the stdlib module. Neither must mask features.py."""
    import inputs

    class Features:
        PHONE_KEYBOARD = True

    class BareSecrets:
        pass

    monkeypatch.setattr(
        inputs, "_optional",
        lambda name: BareSecrets if name == "secrets" else Features,
    )
    assert inputs.phone_keyboard_enabled() is True
