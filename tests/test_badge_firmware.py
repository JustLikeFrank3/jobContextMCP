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
        # Simulated millisecond clock. The app throttles its work-item polling
        # to one call every _POLL_MS, so a test that wants a second poll has
        # to move time forward rather than just calling update() again.
        self.offset_ms = 0

    def advance_ms(self, millis):
        self.offset_ms += millis

    def init(self):
        return True

    def pressed(self, name):
        return name in self.down

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

    def header(self, title, subtitle=""):
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


_APP_MODULES = ("keyboard", "inputs", "screensaver", "tetris", "badgeapp")


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


def test_wifi_says_so_when_nothing_known_is_in_range(monkeypatch):
    import types

    secrets_obj = types.SimpleNamespace(WIFI_NETWORKS=[("Home", "a")])
    wlan = _FakeWlan(visible=["Starbucks WiFi"], joinable=set())
    api = _api_with(monkeypatch, secrets_obj, wlan)
    with pytest.raises(api.ApiError, match="in range"):
        api.connect_wifi()
    assert wlan.tried == []


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
