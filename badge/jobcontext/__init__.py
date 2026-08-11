"""jobcontext — GitHub Universe badge app.

Type a company, see what your pipeline says about it, and queue a tailored
resume or cover letter without taking your phone out at a conference.

    SEARCH  →  RESULTS  →  ACTIONS  →  WORKING  →  DONE
      ▲          │           │                       │
      └──────────┴───────────┴───────────────────────┘  (C backs out)

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
ERROR = "error"

MATERIALS = (("resume", "Resume"), ("cover_letter", "Cover letter"), ("both", "Both"))
_POLL_MS = 2000
_MAX_QUERY = 40

state = SEARCH
query = ""
results = []
selected = 0
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
    _draw_splash("connecting…")
    try:
        _online = api.connect_wifi(status=lambda text: _draw_splash(text))
        if _online:
            api.ping()
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    if not _online:
        _go(ERROR, "wifi failed — check secrets.py")


def on_exit():
    pass


# ── frame ──────────────────────────────────────────────────────────────────────

def update():
    if state == SEARCH:
        _update_search()
    elif state == RESULTS:
        _update_results()
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
    ui.footer("UP/DOWN pick  A type  B delete  C search")


def _run_search():
    global results, selected

    _draw_status("searching " + ui.fit(query.strip(), 20) + "…")
    try:
        body = api.search(query.strip())
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return
    results = body.get("results", [])
    selected = 0
    if not results:
        _go(ERROR, "nothing found for " + ui.fit(query.strip(), 18))
        return
    _go(RESULTS)


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
            _flash("not queued yet — capture it first")
    if _edge("C"):
        query = ""
        _go(SEARCH)
        return

    ui.clear()
    ui.header("results", str(len(results)) + " for " + ui.fit(query.strip(), 18))
    y = 52
    for i, hit in enumerate(results):
        chosen = i == selected
        if chosen:
            ui.rect(0, y - 3, ui.WIDTH, 34, (26, 40, 60))
        ui.text(ui.fit(hit.get("company", ""), 28), 8, y, ui.ACCENT if chosen else ui.WHITE, 2)
        line = ui.fit(hit.get("role", ""), 30)
        score = hit.get("score") or ""
        ui.text(line, 8, y + 16, ui.DIM, 1)
        if score:
            ui.text(score, ui.WIDTH - 40, y + 16, ui.OK, 1)
        y += 34
        if y > ui.HEIGHT - 40:
            break
    ui.footer("UP/DOWN select  A make something  C new search")


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
        _draw_status("queueing " + MATERIALS[action_index][1].lower() + "…")
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
    ui.header(ui.fit(hit.get("company", ""), 24), ui.fit(hit.get("role", ""), 40))
    y = 60
    for i, (_key, label) in enumerate(MATERIALS):
        chosen = i == action_index
        if chosen:
            ui.rect(0, y - 4, ui.WIDTH, 30, (26, 40, 60))
        ui.text(("> " if chosen else "  ") + label, 12, y, ui.ACCENT if chosen else ui.WHITE, 2)
        y += 32
    ui.footer("UP/DOWN choose  A generate  C back")


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
    ui.text("generating" + dots, 12, 100, ui.WHITE, 3)
    ui.text("this runs on the server —", 12, 150, ui.DIM, 1)
    ui.text("the badge can walk away", 12, 164, ui.DIM, 1)
    ui.footer("C cancel waiting")

    if _edge("C"):
        _go(RESULTS)


def _update_terminal():
    global query

    ui.clear()
    if state == DONE:
        ui.header("done", "")
        ui.text("✓", 12, 80, ui.OK, 4)
        ui.text(ui.fit(message, 34), 12, 130, ui.WHITE, 1)
    else:
        ui.header("problem", "")
        ui.text(ui.fit(message, 36), 12, 90, ui.WARN, 1)
        ui.text("A retry   C start over", 12, 140, ui.DIM, 1)

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
    ui.text(ui.fit(text, 34), 12, 100, ui.DIM, 2)
    ui.flip()


def _draw_status(text):
    """Draw before a blocking call so the pause looks intentional."""
    ui.clear()
    ui.header("jobcontext", "")
    ui.text(ui.fit(text, 30), 12, 100, ui.WHITE, 2)
    ui.flip()


def _flash(text):
    global message
    message = text
    _draw_status(text)
    time.sleep(1)
