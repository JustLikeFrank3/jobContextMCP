"""jobcontext — GitHub Universe 2026 badge app.

Type a company, see what your pipeline says about it, and queue a tailored
resume or cover letter without taking your phone out at a conference.

    CONNECTING → SEARCH → RESULTS → ACTIONS → WORKING → DONE
                   ▲         │          │                  │
                   └─────────┴──────────┴──────────────────┘  (BACK backs out)

The 2026 app contract: module code runs once, then `run(update)` calls
update() every frame and presents what it drew when it returns. update()
must not block for long, which shapes two things here:

  * WiFi is polled — wifi.connect() is non-blocking and called every frame
    until it reports connected, with a status screen the whole time.
  * The slow calls (search, enqueue, poll) are *deferred*: the frame that
    asks for one draws "searching..." and returns, so that frame is actually
    shown, and the call runs at the start of the next frame. Drawing a status
    and then blocking in the same update() would never display the status.
"""

import sys

try:
    _APP_DIR = __file__.rsplit("/", 1)[0]
except (NameError, AttributeError):
    _APP_DIR = "/system/apps/jobcontext"
if _APP_DIR and _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

try:  # loaded as a package or flat — support both
    from . import api, inputs, ui
except ImportError:
    import api
    import inputs
    import ui

# States
CONNECTING = "connecting"
SEARCH = "search"
RESULTS = "results"
ACTIONS = "actions"
WORKING = "working"
DONE = "done"
ERROR = "error"

MATERIALS = (("resume", "Resume"), ("cover_letter", "Cover letter"), ("both", "Both"))
_POLL_MS = 2000
_WIFI_TIMEOUT_MS = 30000
_FLASH_MS = 1500
_MAX_QUERY = 40
# Results rows: a size-2 company line (26px) over a size-1 role line (13px).
_ROW_H = 42
_LIST_TOP = 48
_VISIBLE_ROWS = 4

state = CONNECTING
query = ""
results = []
selected = 0
action_index = 0
work_id = 0
message = ""
source = None
_connect_started = 0
_last_poll = 0
_flash_text = ""
_flash_until = 0
_task = None
_task_label = ""
_task_shown = False


def init():
    global source, _connect_started
    ui.init()
    source = inputs.best_available()
    missing = api.configured()
    if missing:
        _go(ERROR, "add " + missing + " to secrets.py")
        return
    _connect_started = ui.ticks()
    _go(CONNECTING)


def on_exit():
    pass


# ── frame ──────────────────────────────────────────────────────────────────────

def update():
    """One frame: handle input for the current screen, then draw whatever
    screen that left us on — each exactly once.

    Separating the two is what keeps a press from leaking across screens:
    the SELECT that moves RESULTS to ACTIONS is consumed by RESULTS' input
    handler, and ACTIONS only *draws* this frame, so it cannot also read that
    SELECT as "generate".
    """
    global _task

    ui.poll()
    if _task is not None and _task_shown:
        # The status for this call was presented last frame and stays on
        # screen while it blocks. Input is skipped: anything pressed during
        # the wait belongs to no screen.
        fn, _task = _task, None
        fn()
    elif _task is None:
        _INPUT[state]()

    if _task is not None:
        _show_task()
        return

    _DRAW[state]()
    if _flash_text and ui.ticks() < _flash_until:
        ui.box(16, 96, ui.WIDTH - 32, 40, ui.PANEL, 6)
        ui.centred(_flash_text, 109, ui.WARN, 1, x=16, span=ui.WIDTH - 32)


def _go(new_state, note=""):
    global state, message
    state = new_state
    if note:
        message = note


def _defer(label, fn):
    """Show *label* this frame; run *fn* at the start of the next one."""
    global _task, _task_label, _task_shown
    _task, _task_label, _task_shown = fn, label, False


def _show_task():
    global _task_shown
    _task_shown = True
    _draw_status(_task_label)


def _flash(text):
    """A non-blocking toast over whatever the current screen draws."""
    global _flash_text, _flash_until
    _flash_text = text
    _flash_until = ui.ticks() + _FLASH_MS


# ── connecting ─────────────────────────────────────────────────────────────────

def _input_connecting():
    if api.wifi_ready():
        _defer("checking jobcontext...", _check_server)
    elif ui.ticks() - _connect_started > _WIFI_TIMEOUT_MS:
        _go(ERROR, "wifi failed - check secrets.py")


def _draw_connecting():
    dots = "." * (1 + (ui.ticks() // 400) % 3)
    _draw_status("connecting to wifi" + dots)


def _check_server():
    try:
        api.ping()
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    _go(SEARCH)


# ── search ─────────────────────────────────────────────────────────────────────

def _input_search():
    global query

    for event in source.poll():
        kind = event[0]
        if kind == "char" and len(query) < _MAX_QUERY:
            query += event[1]
        elif kind == "back":
            query = query[:-1]
        elif kind == "submit" and query.strip():
            _defer("searching " + query.strip() + "...", _run_search)
            return


def _draw_search():
    ui.clear()
    ui.header("jobcontext", "")
    source.draw(query)
    ui.footer(("dpad", "move"), ("SELECT", "type"), ("BACK", "del"), ("MENU", "go"))


def _run_search():
    global results, selected

    try:
        body = api.search(query.strip())
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    results = body.get("results", [])
    selected = 0
    if not results:
        _go(ERROR, "nothing found for " + query.strip())
        return
    _go(RESULTS)


# ── results ────────────────────────────────────────────────────────────────────

def _input_results():
    global selected, query, action_index

    if ui.pressed("UP"):
        selected = (selected - 1) % len(results)
    if ui.pressed("DOWN"):
        selected = (selected + 1) % len(results)
    if ui.pressed("SELECT"):
        # Directory-only hits carry job_id 0: known company, nothing queued to
        # generate against yet.
        if results[selected].get("job_id"):
            action_index = 0
            _go(ACTIONS)
            return
        _flash("not queued yet - capture it first")
    if ui.pressed("BACK"):
        query = ""
        _go(SEARCH)


def _draw_results():
    ui.clear()
    ui.header("results", str(len(results)) + " for " + query.strip())
    # Scroll so the selection is always on screen.
    first = max(0, min(selected - _VISIBLE_ROWS + 1, len(results) - _VISIBLE_ROWS))
    y = _LIST_TOP
    for i in range(first, min(len(results), first + _VISIBLE_ROWS)):
        hit = results[i]
        chosen = i == selected
        if chosen:
            ui.box(4, y - 1, ui.WIDTH - 8, _ROW_H - 2, ui.HIGHLIGHT, 4)
        ui.text(hit.get("company", ""), 12, y, ui.ACCENT if chosen else ui.WHITE, 2, width=ui.WIDTH - 24)
        score = hit.get("score") or ""
        role_y = y + ui.line_height(2)
        ui.text(hit.get("role", ""), 12, role_y, ui.DIM, 1, width=ui.WIDTH - 72)
        if score:
            ui.text(score, ui.WIDTH - 52, role_y, ui.OK, 1, width=44)
        y += _ROW_H
    if len(results) > _VISIBLE_ROWS:
        ui.text(str(selected + 1) + "/" + str(len(results)), ui.WIDTH - 48, ui.HEADER_H + 2, ui.DIM, 1)
    ui.footer(("UPDOWN", "pick"), ("SELECT", "make"), ("BACK", "new search"))


# ── actions ────────────────────────────────────────────────────────────────────

def _input_actions():
    global action_index

    if ui.pressed("UP"):
        action_index = (action_index - 1) % len(MATERIALS)
    if ui.pressed("DOWN"):
        action_index = (action_index + 1) % len(MATERIALS)
    if ui.pressed("BACK"):
        _go(RESULTS)
        return
    if ui.pressed("SELECT"):
        _defer("queueing " + MATERIALS[action_index][1].lower() + "...", _request_materials)


def _request_materials():
    global work_id, _last_poll

    hit = results[selected]
    try:
        body = api.request_materials(hit["job_id"], MATERIALS[action_index][0])
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    work_id = body.get("work_id", 0)
    _last_poll = ui.ticks()
    _go(WORKING)


def _draw_actions():
    hit = results[selected]
    ui.clear()
    ui.header(hit.get("company", ""), hit.get("role", ""))
    y = 56
    for i, (_key, label) in enumerate(MATERIALS):
        chosen = i == action_index
        if chosen:
            ui.box(4, y - 3, ui.WIDTH - 8, ui.line_height(2) + 6, ui.HIGHLIGHT, 4)
        ui.text(("> " if chosen else "  ") + label, 12, y, ui.ACCENT if chosen else ui.WHITE, 2)
        y += 38
    ui.footer(("UPDOWN", "choose"), ("SELECT", "generate"), ("BACK", "back"))


# ── working ────────────────────────────────────────────────────────────────────

def _input_working():
    if ui.pressed("BACK"):
        _go(RESULTS)
        return
    if ui.ticks() - _last_poll >= _POLL_MS:
        # Polled inline rather than deferred: last frame's spinner stays on
        # screen during the call, which is the status we want anyway.
        _poll_work()


def _poll_work():
    global _last_poll

    _last_poll = ui.ticks()
    try:
        body = api.poll(work_id)
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    status = body.get("status", "")
    if status == "succeeded":
        labels = dict(MATERIALS)
        made = [labels.get(key, key).lower() for key in body.get("made") or []]
        _go(DONE, " and ".join(made) + " ready on your desktop" if made else "done")
    elif status == "failed":
        _go(ERROR, body.get("detail") or "generation failed")


def _draw_working():
    ui.clear()
    ui.header("working", "job #" + str(work_id))
    # A spinner, because a static screen during a 30s LLM call reads as a crash.
    dots = "." * (1 + (ui.ticks() // 400) % 3)
    ui.text("generating" + dots, 12, 84, ui.WHITE, 2)
    ui.text("this runs on the server -", 12, 136, ui.DIM, 1)
    ui.text("the badge can walk away", 12, 152, ui.DIM, 1)
    ui.footer(("BACK", "stop waiting"))


# ── done / error ───────────────────────────────────────────────────────────────

def _input_terminal():
    global query, _connect_started

    if api.configured():
        return  # nothing to retry until secrets.py is fixed
    if ui.pressed("BACK"):
        query = ""
        _go(SEARCH)
    elif ui.pressed("SELECT"):
        if not api.wifi_ready():
            _connect_started = ui.ticks()
            _go(CONNECTING)
        else:
            _go(RESULTS if results else SEARCH)


def _draw_terminal():
    ui.clear()
    if state == DONE:
        ui.header("done", "")
        ui.box(12, 56, 48, 48, ui.OK, 24)
        ui.centred("OK", 67, ui.BLACK, 2, x=12, span=48)
        ui.text(message, 12, 120, ui.WHITE, 1, width=ui.WIDTH - 24, lines=4)
        ui.footer(("SELECT", "back to results"), ("BACK", "new search"))
    else:
        ui.header("problem", "")
        # Server errors arrive pre-clipped to one line; local ones (a missing
        # setting, a network failure) can wrap.
        ui.text(message, 12, 60, ui.WARN, 1, width=ui.WIDTH - 24, lines=6)
        ui.footer(("SELECT", "retry"), ("BACK", "new search"))


# ── helpers ────────────────────────────────────────────────────────────────────

def _draw_status(text):
    ui.clear()
    ui.header("jobcontext", "")
    ui.centred(text, (ui.HEIGHT - ui.line_height(2)) // 2, ui.WHITE, 2)


_INPUT = {
    CONNECTING: _input_connecting,
    SEARCH: _input_search,
    RESULTS: _input_results,
    ACTIONS: _input_actions,
    WORKING: _input_working,
    DONE: _input_terminal,
    ERROR: _input_terminal,
}

_DRAW = {
    CONNECTING: _draw_connecting,
    SEARCH: _draw_search,
    RESULTS: _draw_results,
    ACTIONS: _draw_actions,
    WORKING: _draw_working,
    DONE: _draw_terminal,
    ERROR: _draw_terminal,
}


init()
run(update)
