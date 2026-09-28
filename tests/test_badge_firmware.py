"""The badge app, driven on the host against a fake Universe 2026 runtime.

badge/jobcontext/ is MicroPython and never runs in CI, so the interesting
logic — text entry, screen transitions, deferred network calls — would
otherwise only ever be tested by flashing a badge and pressing things.

Only the firmware boundary is faked: the runtime builtins (`badge`, `screen`,
`color`, `BUTTON_*`, `run`, ...) and the `wifi`, `requests` and `secrets`
modules. The app's own modules — ui, api, keyboard, inputs and the state
machine — are the real files.

The fake input model matches the firmware's: `badge.pressed(b)` is true only
on the frame a pad goes down, `badge.held(b)` for every frame it stays down.
"""
from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "badge" / "jobcontext"
_APP_MODULES = ("ui", "api", "keyboard", "inputs")
_BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "MENU", "HOME")
# A stock Tufty 2350 / the Universe 2025 badge: physical buttons only.
_TUFTY_BUTTONS = ("A", "B", "C", "UP", "DOWN", "HOME")


# ── fake runtime ───────────────────────────────────────────────────────────────

class FakeBadge:
    def __init__(self):
        self.ticks = 1000
        self.pressed_now = set()
        self.held_now = set()
        self.modes = []

    def mode(self, flags):
        self.modes.append(flags)

    def pressed(self, button):
        return button in self.pressed_now

    def held(self, button):
        return button in self.held_now


class FakeScreen:
    """Records the strings drawn since the last clear()."""

    def __init__(self):
        self.pen = None
        self.font = None
        self.drawn = []
        self.bounded = []
        self.sizes = {}

    def clear(self):
        self.drawn = []

    def text(self, value, *args, **kwargs):
        self.drawn.append(value)
        # Point form is (x, y, size); rect form is (bounds, size).
        self.sizes[value] = args[2] if len(args) >= 3 else args[1] if len(args) == 2 else 1
        if kwargs.get("overflow") is not None:
            self.bounded.append(value)

    def measure_text(self, value, size=1):
        # The `nope` ROM font as measured in the Badgeware simulator: a 13px
        # line box and ~8px per character at size 1.
        return len(value) * 8 * size, 13 * size

    def shape(self, _shape):
        pass

    def all_text(self):
        return " | ".join(self.drawn)


class _Namespace:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class FakeServer:
    """Stands in for the firmware's `requests`, routing to canned handlers."""

    def __init__(self):
        self.calls = []
        self.results = []
        self.poll_status = "succeeded"
        self.poll_made = ["resume"]
        self.status_code = 200
        self.fail_with = None

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append((method, url, json.loads(data) if data else None, headers))
        if self.fail_with is not None:
            raise self.fail_with
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        if path.startswith("api/badge/search"):
            body = {"results": self.results}
        elif path.startswith("api/badge/materials"):
            body = {"work_id": 7}
        elif path.startswith("api/badge/work/"):
            body = {"status": self.poll_status, "made": self.poll_made, "detail": "nope"}
        else:
            body = {"ok": True}
        return _Response(self.status_code, body)

    def paths(self, prefix):
        return [c for c in self.calls if prefix in c[1]]


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.closed = False

    def json(self):
        return self._body

    def close(self):
        self.closed = True


class Runtime:
    """Everything a test needs to drive the app, plus the loaded app."""

    def __init__(self):
        self.badge = FakeBadge()
        self.screen = FakeScreen()
        self.server = FakeServer()
        self.wifi_up = True
        self.secrets = _Namespace(
            WIFI_SSID="guest",
            WIFI_PASSWORD="pw",
            JOBCONTEXT_URL="https://jobcontext.example",
            JOBCONTEXT_TOKEN="jcmcp_badge",
        )
        self.update = None
        self.app = None

    def mod(self, name):
        """The app's own copy of one of its modules."""
        return getattr(self.app, name)

    # driving helpers
    def frame(self, *pressed, held=None, ms=16):
        """Advance one frame with *pressed* going down this frame."""
        self.badge.ticks += ms
        self.badge.pressed_now = {"BUTTON_" + p for p in pressed}
        still = held if held is not None else pressed
        self.badge.held_now = {"BUTTON_" + h for h in still}
        self.app.update()

    def tap(self, name):
        self.frame(name)
        self.frame()

    def settle(self, frames=3):
        for _ in range(frames):
            self.frame()

    def type(self, text):
        """Type *text* by walking the grid, the way a person would."""
        ROWS, SPACE = self.mod("keyboard").ROWS, self.mod("keyboard").SPACE

        for char in text:
            char = SPACE if char == " " else char
            target = next((r, row.index(char)) for r, row in enumerate(ROWS) if char in row)
            kb = self.app.source.kb
            while kb.row != target[0]:
                self.tap("DOWN")
            while kb.col != target[1]:
                self.tap("RIGHT")
            self.tap("SELECT")


def _unload():
    """Forget every copy of the app's modules. Loaded from its __init__.py,
    the app is a package, so its modules live as badgeapp.<name>; the flat
    names are cleared too in case the fallback import path was taken."""
    for name in list(sys.modules):
        if name == "badgeapp" or name.startswith("badgeapp.") or name in _APP_MODULES:
            del sys.modules[name]
    sys.path[:] = [p for p in sys.path if p != str(_APP)]


def _load(rt, monkeypatch, buttons=_BUTTONS):
    globals_ = {
        "badge": rt.badge,
        "screen": rt.screen,
        "color": _Namespace(rgb=lambda *c: c),
        "shape": _Namespace(rectangle=lambda *a: a, rounded_rectangle=lambda *a: a),
        "rect": lambda *a: a,
        "image": _Namespace(ELLIPSES="ellipses"),
        "font": _Namespace(nope="nope"),
        "HIRES": 1,
        "VSYNC": 2,
        "run": lambda fn: setattr(rt, "update", fn),
    }
    for name in set(_BUTTONS) | set(_TUFTY_BUTTONS):
        monkeypatch.delattr(builtins, "BUTTON_" + name, raising=False)
    for name in buttons:
        globals_["BUTTON_" + name] = "BUTTON_" + name
    for name, value in globals_.items():
        monkeypatch.setattr(builtins, name, value, raising=False)

    monkeypatch.setitem(sys.modules, "secrets", rt.secrets)
    monkeypatch.setitem(sys.modules, "requests", rt.server)
    monkeypatch.setitem(sys.modules, "wifi", _Namespace(connect=lambda: rt.wifi_up))
    _unload()

    spec = importlib.util.spec_from_file_location("badgeapp", _APP / "__init__.py")
    app = importlib.util.module_from_spec(spec)
    sys.modules["badgeapp"] = app
    spec.loader.exec_module(app)  # runs init() and run(update)
    rt.app = app
    return rt


@pytest.fixture()
def rt(monkeypatch):
    """A fresh runtime with the app loaded and sitting on the search screen."""
    runtime = _load(Runtime(), monkeypatch)
    runtime.settle()
    assert runtime.app.state == runtime.app.SEARCH
    yield runtime
    _unload()


@pytest.fixture()
def cold(monkeypatch):
    """A runtime whose app has been loaded but not advanced a single frame."""
    runtime = Runtime()
    yield runtime, monkeypatch
    _unload()


# ── startup ────────────────────────────────────────────────────────────────────

def test_boot_requests_hires_and_hands_update_to_run(rt):
    assert rt.badge.modes == [1 | 2]
    assert rt.update is rt.app.update


def test_boot_waits_for_wifi_then_pings(cold):
    rt, monkeypatch = cold
    rt.wifi_up = False
    _load(rt, monkeypatch)

    rt.settle(5)
    assert rt.app.state == rt.app.CONNECTING
    assert "connecting to wifi" in rt.screen.all_text()
    assert rt.server.calls == []

    rt.wifi_up = True
    rt.frame()  # sees wifi, defers the ping and shows its status
    assert "checking jobcontext" in rt.screen.all_text()
    assert rt.server.calls == [], "the status frame must be presented before the call blocks"
    rt.frame()  # runs the ping
    assert rt.server.paths("/api/badge/ping")
    assert rt.app.state == rt.app.SEARCH


def test_wifi_timeout_is_an_error_with_a_retry(cold):
    rt, monkeypatch = cold
    rt.wifi_up = False
    _load(rt, monkeypatch)

    rt.frame(ms=31000)
    assert rt.app.state == rt.app.ERROR
    assert "wifi failed" in rt.app.message

    rt.tap("SELECT")
    assert rt.app.state == rt.app.CONNECTING, "retry must reconnect, not search offline"


def test_missing_token_names_the_setting_and_does_not_retry(cold):
    rt, monkeypatch = cold
    rt.secrets.JOBCONTEXT_TOKEN = ""
    _load(rt, monkeypatch)

    rt.settle()
    assert rt.app.state == rt.app.ERROR
    assert rt.app.message == "add JOBCONTEXT_TOKEN to secrets.py"
    rt.tap("SELECT")
    rt.tap("BACK")
    assert rt.app.state == rt.app.ERROR
    assert rt.server.calls == []


def test_legacy_secret_names_still_work(cold):
    """Badges set up for the 2025 build used BASE_URL / BADGE_TOKEN."""
    rt, monkeypatch = cold
    del rt.secrets.JOBCONTEXT_URL, rt.secrets.JOBCONTEXT_TOKEN
    rt.secrets.BASE_URL = "https://legacy.example/"
    rt.secrets.BADGE_TOKEN = "jcmcp_old"
    _load(rt, monkeypatch)
    rt.settle()

    _method, url, _body, headers = rt.server.calls[0]
    assert url == "https://legacy.example/api/badge/ping"
    assert headers["Authorization"] == "Bearer jcmcp_old"


# ── text entry ─────────────────────────────────────────────────────────────────

def test_grid_typing_builds_a_query(rt):
    rt.tap("SELECT")  # cursor starts on 'A'
    rt.tap("RIGHT")
    rt.tap("SELECT")
    assert rt.app.query == "AB"

    rt.tap("BACK")
    assert rt.app.query == "A"


def test_every_character_is_reachable(rt):
    rt.type("AT&T 3M-O'K.")
    assert rt.app.query == "AT&T 3M-O'K."


def test_movement_wraps_on_both_axes(rt):
    kb_mod = rt.mod("keyboard")
    DELETE, ROWS, SPACE = kb_mod.DELETE, kb_mod.ROWS, kb_mod.SPACE

    rt.tap("LEFT")  # A → J, same row
    assert rt.app.source.kb.current() == "J"

    rt.tap("RIGHT")  # J → A
    rt.tap("UP")  # top row wraps to the action row
    assert rt.app.source.kb.current() == SPACE
    rt.tap("SELECT")
    assert rt.app.query == " "

    rt.tap("RIGHT")
    assert rt.app.source.kb.current() == DELETE
    rt.tap("SELECT")
    assert rt.app.query == ""
    assert len(ROWS[-1]) == 3


def test_column_position_is_kept_across_rows_of_different_length(rt):
    """From the far right of a letter row, DOWN into the three-key action row
    should land on its right-hand key, not clamp to index 2 by accident or
    wrap to the left."""
    SEARCH = rt.mod("keyboard").SEARCH

    for _ in range(9):
        rt.tap("RIGHT")  # 'J'
    for _ in range(4):
        rt.tap("DOWN")
    assert rt.app.source.kb.current() == SEARCH


def test_held_direction_repeats_after_a_delay(rt):
    kb = rt.app.source.kb
    rt.frame("RIGHT", ms=16)  # the press itself: one step
    assert kb.col == 1
    for _ in range(20):  # 320ms held — still inside the repeat delay
        rt.frame(held=["RIGHT"], ms=16)
    assert kb.col == 1
    for _ in range(40):  # ~640ms more: a few repeats at ~110ms each
        rt.frame(held=["RIGHT"], ms=16)
    assert kb.col >= 5
    rt.frame()
    col = kb.col
    rt.frame(held=["RIGHT"], ms=500)
    assert kb.col == col, "a release must reset the repeat timer"


def test_go_key_with_an_empty_query_does_nothing(rt):
    SEARCH = rt.mod("keyboard").SEARCH

    rt.tap("UP")
    rt.tap("RIGHT")
    rt.tap("RIGHT")
    assert rt.app.source.kb.current() == SEARCH
    rt.tap("SELECT")
    rt.settle()
    assert rt.app.state == rt.app.SEARCH
    assert rt.server.paths("/search") == []


# ── search ─────────────────────────────────────────────────────────────────────

def test_menu_submits_and_the_status_frame_precedes_the_call(rt):
    rt.server.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": "8/10"}]
    rt.app.query = "ACME"

    rt.frame("MENU")
    assert "searching ACME..." in rt.screen.all_text()
    assert rt.server.paths("/search") == [], "must draw the status before blocking"

    rt.frame()
    (call,) = rt.server.paths("/search")
    assert call[1].endswith("/api/badge/search?q=ACME&limit=6")
    assert rt.app.state == rt.app.RESULTS
    assert "Acme" in rt.screen.drawn, "results draw on the same frame the call returns"


def test_query_is_percent_encoded(rt):
    rt.app.query = "AT&T CO."
    rt.frame("MENU")
    rt.frame()
    url = rt.server.paths("/search")[0][1]
    assert "q=AT%26T+CO.&" in url


def test_held_select_does_not_leak_into_the_next_screen(rt):
    """The press that leaves a screen must not also actuate the next one.
    SELECT on a result opens ACTIONS; if ACTIONS read that same press it
    would queue a resume nobody chose."""
    rt.server.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": ""}]
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    assert rt.app.state == rt.app.RESULTS

    rt.frame("SELECT")
    assert rt.app.state == rt.app.ACTIONS
    for _ in range(10):
        rt.frame(held=["SELECT"])
    rt.settle()
    assert rt.app.state == rt.app.ACTIONS
    assert rt.server.paths("/materials") == []


def test_empty_results_are_an_explicit_message(rt):
    rt.app.query = "NOBODY"
    rt.frame("MENU")
    rt.frame()
    assert rt.app.state == rt.app.ERROR
    assert rt.app.message == "nothing found for NOBODY"


def test_directory_hit_cannot_start_a_generation(rt):
    """job_id 0 means 'known company, nothing queued' — offering to generate
    from it would produce a resume against an empty job description."""
    rt.server.results = [{"job_id": 0, "company": "Initech", "role": "Austin, TX", "score": ""}]
    rt.app.query = "INITECH"
    rt.frame("MENU")
    rt.frame()

    rt.tap("SELECT")
    assert rt.app.state == rt.app.RESULTS
    assert "not queued yet - capture it first" in rt.screen.drawn
    rt.frame(ms=2000)
    assert "not queued yet - capture it first" not in rt.screen.drawn, "the toast expires"


def test_long_result_lists_scroll_to_keep_the_selection_visible(rt):
    rt.server.results = [
        {"job_id": i + 1, "company": "Company %d" % i, "role": "Role", "score": ""} for i in range(6)
    ]
    rt.app.query = "CO"
    rt.frame("MENU")
    rt.frame()
    assert "Company 0" in rt.screen.drawn

    for _ in range(5):
        rt.tap("DOWN")
    assert "Company 5" in rt.screen.drawn
    assert "Company 0" not in rt.screen.drawn
    assert "6/6" in rt.screen.drawn

    rt.tap("DOWN")  # wraps to the top
    assert "Company 0" in rt.screen.drawn


def test_back_from_results_starts_a_new_search(rt):
    rt.server.results = [{"job_id": 3, "company": "Acme", "role": "SWE", "score": ""}]
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    rt.tap("BACK")
    assert rt.app.state == rt.app.SEARCH
    assert rt.app.query == ""


def test_text_boxes_are_at_least_one_measured_line_tall(rt):
    """Regression: a text rect shorter than the font's real line box means no
    line 'fits' — the firmware then neither wraps nor adds an ellipsis, it
    just cuts the glyphs off at the bottom. Heights come from measure_text."""
    ui = rt.mod("ui")
    assert ui.line_height(1) == 13
    assert ui.line_height(2) == 26


def test_status_lines_shrink_rather_than_overflow(rt):
    """A status line carries user-typed text, so it steps down a size when
    it would not fit at the default one."""
    rt.app.query = "CONSOLIDATED AEROSPACE"
    rt.frame("MENU")
    status = "searching CONSOLIDATED AEROSPACE..."
    assert len(status) * 8 * 2 > 320 >= len(status) * 8, "fixture should need the smaller size"
    assert status in rt.screen.drawn
    assert rt.screen.sizes[status] == 1

    rt.frame()  # runs the search: no results, so the error screen
    rt.tap("BACK")  # back to a fresh search
    rt.app.query = "ACME"
    rt.frame("MENU")
    assert rt.screen.sizes["searching ACME..."] == 2, "short statuses keep the large size"


def test_long_names_are_clipped_by_the_firmware_not_guessed(rt):
    """Result text is drawn into a rect with overflow=ELLIPSES, so the
    firmware measures and truncates — no hard-coded character width."""
    long_name = "An Extremely Long Company Name That Cannot Possibly Fit, Incorporated"
    rt.server.results = [{"job_id": 3, "company": long_name, "role": "SWE", "score": ""}]
    rt.app.query = "AN"
    rt.frame("MENU")
    rt.frame()
    assert long_name in rt.screen.bounded


# ── generation ─────────────────────────────────────────────────────────────────

def _to_actions(rt, job_id=42):
    rt.server.results = [{"job_id": job_id, "company": "Acme", "role": "SWE", "score": "8/10"}]
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    rt.tap("SELECT")
    assert rt.app.state == rt.app.ACTIONS


def test_full_generation_flow(rt):
    _to_actions(rt)
    rt.server.poll_status = "running"
    rt.tap("DOWN")  # resume → cover letter
    rt.frame("SELECT")
    assert "queueing cover letter..." in rt.screen.all_text()
    rt.frame()
    (call,) = rt.server.paths("/materials")
    assert call[0] == "POST"
    assert call[2] == {"job_id": 42, "material": "cover_letter"}
    assert rt.app.state == rt.app.WORKING

    rt.settle(10)  # 160ms: too soon to poll
    assert rt.server.paths("/work/") == []

    rt.frame(ms=2000)
    assert len(rt.server.paths("/work/7")) == 1
    assert rt.app.state == rt.app.WORKING, "a still-running job keeps waiting"
    rt.frame()
    assert len(rt.server.paths("/work/7")) == 1, "polling is throttled, not per-frame"

    rt.server.poll_status = "succeeded"
    rt.server.poll_made = ["cover_letter"]
    rt.frame(ms=2000)
    assert rt.app.state == rt.app.DONE
    assert rt.app.message == "cover letter ready on your desktop"

    rt.tap("SELECT")
    assert rt.app.state == rt.app.RESULTS


def test_both_materials_read_as_a_sentence(rt):
    _to_actions(rt)
    rt.server.poll_made = ["resume", "cover_letter"]
    rt.frame("SELECT")
    rt.frame()
    rt.frame(ms=2000)
    assert rt.app.message == "resume and cover letter ready on your desktop"


def test_failed_generation_surfaces_detail(rt):
    _to_actions(rt)
    rt.server.poll_status = "failed"
    rt.frame("SELECT")
    rt.frame()
    rt.frame(ms=2000)
    assert rt.app.state == rt.app.ERROR
    assert rt.app.message == "nope"


def test_back_stops_waiting_without_cancelling_the_job(rt):
    _to_actions(rt)
    rt.server.poll_status = "running"
    rt.frame("SELECT")
    rt.frame()
    rt.tap("BACK")
    assert rt.app.state == rt.app.RESULTS


# ── transport ──────────────────────────────────────────────────────────────────

def test_network_failure_during_search_is_caught(rt):
    """A dropped conference network must not traceback into the frame loop."""
    rt.server.fail_with = OSError("ETIMEDOUT")
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    assert rt.app.state == rt.app.ERROR
    assert rt.app.message.startswith("network:")


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (403, "token is not badge-scoped"),
        (401, "token rejected - regenerate it"),
        (500, "server said 500"),
    ],
)
def test_http_errors_become_readable_messages(rt, status, message):
    rt.server.status_code = status
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    assert rt.app.message == message


def test_every_request_carries_the_badge_token(rt):
    rt.app.query = "ACME"
    rt.frame("MENU")
    rt.frame()
    for _method, _url, _body, headers in rt.server.calls:
        assert headers["Authorization"] == "Bearer jcmcp_badge"


def test_ble_source_is_declared_unavailable(rt):
    """The BLE keyboard is wired in but not implemented; best_available must
    therefore hand back the pads rather than a source that emits nothing."""
    inputs = rt.mod("inputs")

    assert inputs.BleKeyboardInput().available() is False
    assert isinstance(inputs.best_available(), inputs.ButtonInput)


# ── physical buttons (stock Tufty 2350 / Universe 2025 badge) ─────────────────

@pytest.fixture()
def tufty(monkeypatch):
    """The app on a badge with A/B/C/UP/DOWN buttons instead of 2026 pads."""
    runtime = _load(Runtime(), monkeypatch, buttons=_TUFTY_BUTTONS)
    runtime.settle()
    assert runtime.app.state == runtime.app.SEARCH
    yield runtime
    _unload()


def _tap_b(rt):
    """A short B press: down, a couple of frames, up."""
    rt.frame("B")
    rt.frame(held=["B"])
    rt.frame()


def _hold_b(rt, ms=700):
    rt.frame("B")
    rt.frame(held=["B"], ms=ms)
    rt.frame()


def test_buttons_mode_is_chosen_when_pads_are_absent(tufty):
    assert tufty.mod("ui").controls == "buttons"


def test_pads_mode_on_the_2026_badge(rt):
    assert rt.mod("ui").controls == "pads"


def test_a_and_c_move_left_and_right(tufty):
    kb = tufty.app.source.kb
    tufty.tap("C")
    assert kb.col == 1
    tufty.tap("A")
    tufty.tap("A")
    assert kb.current() == "J", "A from the first column wraps like LEFT"


def test_tapping_b_types_on_release(tufty):
    tufty.frame("B")
    assert tufty.app.query == "", "SELECT waits for release — it might become BACK"
    tufty.frame()
    assert tufty.app.query == "A"


def test_holding_b_is_back_and_does_not_also_type(tufty):
    _tap_b(tufty)
    _tap_b(tufty)
    assert tufty.app.query == "AA"

    tufty.frame("B")
    tufty.frame(held=["B"], ms=300)
    assert tufty.app.query == "AA", "not long enough to be BACK yet"
    tufty.frame(held=["B"], ms=400)
    assert tufty.app.query == "A", "BACK fires while still held, at the threshold"
    for _ in range(10):
        tufty.frame(held=["B"], ms=100)
    assert tufty.app.query == "A", "one long press is one BACK"
    tufty.frame()
    assert tufty.app.query == "A", "releasing a long press must not type"


def test_full_flow_on_buttons(tufty):
    """Search via the on-screen search key (there is no MENU button), pick a
    result, generate, and back out — every screen reachable."""
    tufty.server.results = [
        {"job_id": 42, "company": "Acme", "role": "SWE", "score": ""},
        {"job_id": 43, "company": "Acme Labs", "role": "SRE", "score": ""},
    ]
    tufty.app.query = "ACME"
    kb = tufty.app.source.kb
    while kb.row != 4:
        tufty.tap("UP")
    while kb.current() != tufty.mod("keyboard").SEARCH:
        tufty.tap("C")
    _tap_b(tufty)
    tufty.settle()
    assert tufty.app.state == tufty.app.RESULTS

    tufty.tap("DOWN")
    _tap_b(tufty)
    assert tufty.app.state == tufty.app.ACTIONS
    _hold_b(tufty)
    assert tufty.app.state == tufty.app.RESULTS, "hold B backs out of the menu"

    _tap_b(tufty)
    _tap_b(tufty)
    tufty.settle()
    assert tufty.server.paths("/materials")[0][2] == {"job_id": 43, "material": "resume"}
    assert tufty.app.state == tufty.app.WORKING


def test_legend_names_the_buttons_in_hand(tufty):
    assert "B type" in tufty.screen.drawn[-1]
    assert "hold B del" in tufty.screen.drawn[-1]
    assert "MENU" not in tufty.screen.drawn[-1], "no MENU button to name"
