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

    def connect_wifi(self, status=None):
        return True

    def ping(self):
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
        return {"status": self.poll_status, "made": self.poll_made, "detail": "nope"}


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
    for name in ("keyboard", "inputs", "badgeapp"):
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
    for name in ("keyboard", "inputs", "badgeapp"):
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
