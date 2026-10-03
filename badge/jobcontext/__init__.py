"""jobcontext — GitHub Universe badge app.

Type a company, see what your pipeline says about it — or find its open roles
on the web — and queue a tailored resume or cover letter without taking your
phone out at a conference.

    SEARCH  →  RESULTS  →  ACTIONS  →  WORKING  →  DONE
      │           │ B         ▲
      │ (none)    ▼           │ A adds the role to the pipeline
      └──────→  JOBS  ────────┘
                                          C backs out to SEARCH from anywhere

The badgeware app contract: init() once, update() every frame, on_exit() on
the way out. update() must not block for long, which is why the only slow
things here (search, enqueue, poll) draw a frame *before* they call out and
poll on an interval rather than every pass.
"""

import time

try:  # loaded as a package (/apps/jobcontext) or flat — support both
    from . import api, inputs, ui
except ImportError:
    import api
    import inputs
    import ui

# States
SEARCH = "search"
RESULTS = "results"
ACTIONS = "actions"
WORKING = "working"
DONE = "done"
JOBS = "jobs"
ERROR = "error"

MATERIALS = (("resume", "Resume"), ("cover_letter", "Cover letter"), ("both", "Both"))
_POLL_MS = 2000
_MAX_QUERY = 40
_ROWS = 3
_ROW_H = 24

state = SEARCH
query = ""
results = []
selected = 0
jobs = []
job_search_id = ""
job_selected = 0
action_index = 0
work_id = 0
message = ""
source = None
_online = False
_last_poll = 0
_prev_buttons = {}


def init():
    global source, _online
    ui.init()
    source = inputs.best_available()
    _draw_splash("connecting...")
    try:
        _online = api.connect_wifi(status=lambda text: _draw_splash(text))
        if _online:
            api.ping()
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    if not _online:
        _go(ERROR, "wifi failed - check secrets.py")


def on_exit():
    pass


# ── frame ──────────────────────────────────────────────────────────────────────

def update():
    if state == SEARCH:
        _update_search()
    elif state == RESULTS:
        _update_results()
    elif state == JOBS:
        _update_jobs()
    elif state == ACTIONS:
        _update_actions()
    elif state == WORKING:
        _update_working()
    else:
        _update_terminal()
    ui.flip()


def _edge(name):
    """One-shot button read for the screens that don't use the input source."""
    down = ui.pressed(name)
    fired = down and not _prev_buttons.get(name, False)
    _prev_buttons[name] = down
    return fired


def _go(new_state, note=""):
    """Change screen, re-arming every button first.

    The search screen reads buttons through the input source and the other
    screens read them through _edge(); those are two independent edge
    detectors. Without re-arming, the C press that submits a search is still
    physically down when RESULTS first reads it, so RESULTS sees a fresh press
    and bounces straight back to SEARCH. Same for A moving into ACTIONS and
    immediately confirming a generation nobody chose.
    """
    global state, message
    state = new_state
    if note:
        message = note
    for name in ("UP", "DOWN", "A", "B", "C"):
        _prev_buttons[name] = ui.pressed(name)
    if source is not None:
        source.rearm()


# ── search ─────────────────────────────────────────────────────────────────────

def _update_search():
    global query

    for event in source.poll():
        kind = event[0]
        if kind == "char" and len(query) < _MAX_QUERY:
            query += event[1]
        elif kind == "back":
            query = query[:-1]
        elif kind == "submit" and query.strip():
            _run_search()
            return

    ui.clear()
    ui.header("jobcontext", "who are you talking to?")
    source.draw(query)
    ui.footer("U/D pick  A type  B del  C search")


def _run_search():
    global results, selected

    _draw_status("searching " + query.strip() + "...")
    try:
        body = api.search(query.strip())
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    results = body.get("results", [])
    selected = 0
    if not results:
        # Nothing in the pipeline yet — the usual case for a company you just
        # met — so go find its open roles instead of dead-ending.
        _run_job_search()
        return
    _go(RESULTS)


def _run_job_search():
    global jobs, job_search_id, job_selected

    _draw_status("finding open roles for " + query.strip() + "...")
    try:
        body = api.jobs(query.strip())
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    jobs = body.get("results", [])
    job_search_id = body.get("search_id", "")
    job_selected = 0
    if not jobs:
        _go(ERROR, "no open roles found for " + query.strip())
        return
    _go(JOBS)


# ── results ────────────────────────────────────────────────────────────────────

def _update_results():
    global selected, query

    if _edge("UP"):
        selected = (selected - 1) % len(results)
    if _edge("DOWN"):
        selected = (selected + 1) % len(results)
    if _edge("A"):
        # Directory-only hits carry job_id 0: known company, nothing queued to
        # generate against yet.
        if results[selected].get("job_id"):
            _go(ACTIONS)
        else:
            _flash("not queued yet - capture it first")
    if _edge("B"):
        _run_job_search()
        return
    if _edge("C"):
        query = ""
        _go(SEARCH)
        return

    ui.clear()
    ui.header("results", str(len(results)) + " for " + query.strip())
    # Three rows fit between header and footer; scroll so the selection is
    # always on screen with one row of context above it where possible.
    first = max(0, min(selected - 1, len(results) - _ROWS))
    y = 30
    for i in range(first, min(first + _ROWS, len(results))):
        hit = results[i]
        chosen = i == selected
        if chosen:
            ui.rect(0, y - 2, ui.WIDTH, _ROW_H, ui.SELECT)
        ui.text(ui.fit(hit.get("company", ""), ui.WIDTH - 8, 2), 4, y, ui.ACCENT if chosen else ui.WHITE, 2)
        score = hit.get("score") or ""
        room = ui.WIDTH - 8
        if score:
            score_w = ui.text_width(score, 1)
            ui.text(score, ui.WIDTH - 4 - score_w, y + 10, ui.OK, 1)
            room -= score_w + 4
        ui.text(ui.fit(hit.get("role", ""), room, 1), 4, y + 10, ui.DIM, 1)
        y += _ROW_H
    ui.footer("U/D select  A make  B web jobs  C new")


# ── jobs (open roles from the web) ─────────────────────────────────────────────

def _update_jobs():
    global job_selected, results, selected, query

    if _edge("UP"):
        job_selected = (job_selected - 1) % len(jobs)
    if _edge("DOWN"):
        job_selected = (job_selected + 1) % len(jobs)
    if _edge("A"):
        hit = jobs[job_selected]
        _draw_status("adding " + hit.get("company", "") + " to your pipeline...")
        try:
            body = api.queue_job(job_search_id, hit.get("number", job_selected + 1))
        except api.ApiError as exc:
            _go(ERROR, str(exc))
            return
        # The role is a pipeline job now; hand ACTIONS a one-row result list
        # so the existing resume / cover letter flow runs against it as-is.
        results = [{
            "job_id": body.get("job_id", 0),
            "company": body.get("company", hit.get("company", "")),
            "role": body.get("role", hit.get("role", "")),
            "score": "",
        }]
        selected = 0
        _go(ACTIONS)
        return
    if _edge("C"):
        query = ""
        _go(SEARCH)
        return

    ui.clear()
    ui.header("open roles", str(len(jobs)) + " for " + query.strip())
    first = max(0, min(job_selected - 1, len(jobs) - _ROWS))
    y = 30
    for i in range(first, min(first + _ROWS, len(jobs))):
        hit = jobs[i]
        chosen = i == job_selected
        if chosen:
            ui.rect(0, y - 2, ui.WIDTH, _ROW_H, ui.SELECT)
        ui.text(ui.fit(hit.get("company", ""), ui.WIDTH - 8, 2), 4, y, ui.ACCENT if chosen else ui.WHITE, 2)
        detail = hit.get("role", "")
        if hit.get("location"):
            detail += " - " + hit["location"]
        ui.text(ui.fit(detail, ui.WIDTH - 8, 1), 4, y + 10, ui.DIM, 1)
        y += _ROW_H
    ui.footer("U/D select  A add + make  C new")


# ── actions ────────────────────────────────────────────────────────────────────

def _update_actions():
    global action_index, work_id

    if _edge("UP"):
        action_index = (action_index - 1) % len(MATERIALS)
    if _edge("DOWN"):
        action_index = (action_index + 1) % len(MATERIALS)
    if _edge("C"):
        _go(RESULTS)
        return
    if _edge("A"):
        hit = results[selected]
        _draw_status("queueing " + MATERIALS[action_index][1].lower() + "...")
        try:
            body = api.request_materials(hit["job_id"], MATERIALS[action_index][0])
        except api.ApiError as exc:
            _go(ERROR, str(exc))
            return
        work_id = body.get("work_id", 0)
        _go(WORKING)
        return

    hit = results[selected]
    ui.clear()
    ui.header(hit.get("company", ""), hit.get("role", ""))
    y = 32
    for i, (_key, label) in enumerate(MATERIALS):
        chosen = i == action_index
        if chosen:
            ui.rect(0, y - 2, ui.WIDTH, 16, ui.SELECT)
        ui.text(("> " if chosen else "  ") + label, 6, y, ui.ACCENT if chosen else ui.WHITE, 2)
        y += 18
    ui.footer("U/D choose  A generate  C back")


# ── working / terminal ─────────────────────────────────────────────────────────

def _update_working():
    global _last_poll

    now = time.ticks_ms()
    if time.ticks_diff(now, _last_poll) >= _POLL_MS:
        _last_poll = now
        try:
            body = api.poll(work_id)
        except api.ApiError as exc:
            _go(ERROR, str(exc))
            return
        status = body.get("status", "")
        if status == "succeeded":
            made = body.get("made") or []
            _go(DONE, ", ".join(made) + " ready on your desktop" if made else "done")
            return
        if status == "failed":
            _go(ERROR, body.get("detail") or "generation failed")
            return

    ui.clear()
    ui.header("working", "job #" + str(work_id))
    # A spinner, because a static screen during a 30s LLM call reads as a crash.
    dots = "." * (1 + (time.ticks_ms() // 400) % 3)
    ui.text("generating" + dots, 6, 38, ui.WHITE, 3)
    ui.text("this runs on the server -", 6, 66, ui.DIM, 1)
    ui.text("the badge can walk away", 6, 78, ui.DIM, 1)
    ui.footer("C stop waiting")

    if _edge("C"):
        _go(RESULTS)


def _update_terminal():
    global query

    ui.clear()
    if state == DONE:
        ui.header("done", "")
        ui.text("ready", 6, 22, ui.OK, 3)
        _draw_lines(message, 46, ui.WHITE)
    else:
        ui.header("problem", "")
        _draw_lines(message, 24, ui.WARN)

    ui.footer("A retry  C new search")
    if _edge("C"):
        query = ""
        _go(SEARCH)
    elif _edge("A"):
        _go(RESULTS if results else SEARCH)


# ── helpers ────────────────────────────────────────────────────────────────────

def _draw_splash(text):
    ui.clear()
    ui.header("jobcontext", "")
    _draw_lines(text, 50, ui.DIM, 2)
    ui.present()


def _draw_status(text):
    """Draw before a blocking call so the pause looks intentional."""
    ui.clear()
    ui.header("jobcontext", "")
    _draw_lines(text, 50, ui.WHITE, 2)
    ui.present()


def _flash(text):
    global message
    message = text
    _draw_status(text)
    time.sleep(1)


def _draw_lines(text, y, colour, scale=1):
    """Word-wrapped block at the left margin, starting at *y*."""
    step = ui.line_height(scale) + 1
    for line in ui.wrap(text, ui.WIDTH - 12, scale):
        ui.text(line, 6, y, colour, scale)
        y += step
