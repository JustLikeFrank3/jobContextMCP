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

    WIDTH, HEIGHT = 320, 240
    BLACK = WHITE = DIM = ACCENT = WARN = BAD = OK = (0, 0, 0)

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

    def fit(self, value, chars):
        value = str(value)
        return value if len(value) <= chars else value[: chars - 1] + "."

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

    def connect_wifi(self, status=None):
        return True

    def ping(self):
        return {"ok": True}

    def search(self, query, limit=6):
        self.searched.append(query)
        return {"results": self.results}

    def request_materials(self, job_id, material="resume"):
        self.requested.append((job_id, material))
        return {"work_id": 7}

    def poll(self, work_id):
        return {"status": self.poll_status, "made": self.poll_made, "detail": "nope"}


@pytest.fixture()
def badge_app(monkeypatch):
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


def test_empty_results_are_an_explicit_message(badge_app):
    app, ui_, api_ = badge_app
    api_.results = []
    app.query = "NOBODY"
    _tap(app, ui_, "C")
    assert app.state == app.ERROR
    assert "nothing found" in app.message


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
    _tap(app, ui_, "A")               # confirm
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
