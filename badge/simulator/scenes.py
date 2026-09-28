# Renders every screen of the jobcontext badge app inside the Badgeware web
# simulator (run by render.mjs). The simulator models the stock Tufty 2350
# (A/B/C/UP/DOWN/HOME), so the app runs in its physical-buttons mode, and the
# network is faked. Screens are forced by setting app state directly;
# each scene prints "SCENE <name>" and render.mjs captures a few frames later.
import builtins, sys

# render.mjs prepends PADS = True/False (CONTROLS=buttons to get False). With
# PADS, the 2026 pad constants are defined, so the app picks its pads mode
# and legends; without, it runs its physical-buttons (Tufty) mode, which is
# what this simulator's hardware actually is.
if PADS:
    builtins.BUTTON_LEFT = BUTTON_A
    builtins.BUTTON_RIGHT = BUTTON_C
    builtins.BUTTON_SELECT = BUTTON_B
    builtins.BUTTON_BACK = object()
    builtins.BUTTON_MENU = object()


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._b = body
    def json(self):
        return self._b
    def close(self):
        pass

class _Requests:
    def request(self, method, url, data=None, headers=None, timeout=None):
        if "/search" in url:
            return _Resp({"results": RESULTS})
        if "/materials" in url:
            return _Resp({"work_id": 42})
        if "/work/" in url:
            return _Resp({"status": "running"})
        return _Resp({"ok": True})

# Fictional companies only — these renders end up in the README.
RESULTS = [
    {"job_id": 11, "company": "Contoso", "role": "Software Engineer, Agent Infrastructure", "score": "9/10"},
    {"job_id": 12, "company": "Cobalt Labs", "role": "Senior Full Stack / Technical Lead (AI, MCP, Agents)", "score": "8/10"},
    {"job_id": 0, "company": "Consolidated Aerospace Holdings International", "role": "Austin, TX", "score": ""},
    {"job_id": 14, "company": "Copperline", "role": "Backend Engineer", "score": "6/10"},
    {"job_id": 15, "company": "Cortex Dynamics", "role": "Platform Engineer", "score": "5/10"},
    {"job_id": 16, "company": "Corvid Health", "role": "Research Engineer", "score": "7/10"},
]

class _Wifi:
    up = False
    def connect(self):
        return self.up
_wifi = _Wifi()
sys.modules["wifi"] = _wifi
sys.modules["requests"] = _Requests()
class _Secrets:
    pass
_secrets = _Secrets()
_secrets.WIFI_SSID = "universe-guest"
_secrets.JOBCONTEXT_URL = "https://jobcontext.ai"
_secrets.JOBCONTEXT_TOKEN = "jcmcp_demo"
sys.modules["secrets"] = _secrets

_real_run = getattr(builtins, 'run', None)
_captured = []
builtins.run = lambda fn: _captured.append(fn)
sys.path.insert(0, "/apps")
import jobcontext as app
if _real_run is not None:
    builtins.run = _real_run


def s_connecting():
    pass

def s_search_empty():
    _wifi.up = True
    app.state = app.SEARCH

def s_search_typed():
    app.query = "CONTOSO"
    app.source.kb.row, app.source.kb.col = 1, 3

def s_search_action_row():
    app.query = "CONSOLIDATED AEROSPACE HOLD"  # longer than the entry line
    app.source.kb.row, app.source.kb.col = 4, 2

def s_results():
    app.results = RESULTS
    app.selected = 1
    app.query = "CO"
    app.state = app.RESULTS

def s_results_long():
    app.selected = 2

def s_results_scrolled():
    app.selected = 5

def s_toast():
    app.selected = 2
    app._flash("not queued yet - capture it first")

def s_actions():
    app.selected = 1
    app.action_index = 1
    app.state = app.ACTIONS

def s_working():
    app.work_id = 42
    app._last_poll = badge.ticks + 10**7  # no polls during the shot
    app.state = app.WORKING

def s_done():
    app.message = "cover letter ready on your desktop"
    app.state = app.DONE

def s_error():
    app.message = "token is not badge-scoped - mint a 'Badge only' key under API Keys"
    app.state = app.ERROR

SCENES = [
    ("01-connecting", s_connecting),
    ("02-search", s_search_empty),
    ("03-search-typed", s_search_typed),
    ("04-search-action-row", s_search_action_row),
    ("05-results", s_results),
    ("06-results-long-name", s_results_long),
    ("07-results-scrolled", s_results_scrolled),
    ("08-toast", s_toast),
    ("09-actions", s_actions),
    ("10-working", s_working),
    ("11-done", s_done),
    ("12-error", s_error),
]
_SCENE_MS = 1800
_start = None
_index = -1

def driver():
    global _start, _index
    if _start is None:
        _start = badge.ticks
    due = (badge.ticks - _start) // _SCENE_MS
    if due > _index and due < len(SCENES):
        _index = due
        name, fn = SCENES[_index]
        fn()
        print("SCENE " + name)
    app.update()

if _real_run is not None:
    _real_run(driver)
else:
    while True:  # this simulator build has no run(); examples loop themselves
        driver()
        badge.update()
