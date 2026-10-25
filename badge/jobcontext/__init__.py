"""jobcontext — GitHub Universe badge app.

Type a company, see what your pipeline says about it — or find its open roles
on the web — and queue a tailored resume or cover letter without taking your
phone out at a conference.

    SEARCH  →  RESULTS  →  ACTIONS  →  STYLE  →  WORKING  →  DONE
      │           │ B         ▲
      │ (none)    ▼           │ A adds the role to the pipeline
      └──────→  JOBS  ────────┘
                                          C backs out to SEARCH from anywhere

The badgeware app contract: init() once, update() every frame, on_exit() on
the way out. update() must not block for long, which is why the only slow
things here (search, enqueue, poll) draw a frame *before* they call out and
poll on an interval rather than every pass.
"""

import json
import time

try:  # loaded as a package (/apps/jobcontext) or flat — support both
    from . import api, inputs, screensaver, ui
except ImportError:
    import api
    import inputs
    import screensaver
    import ui

# States
SEARCH = "search"
RESULTS = "results"
ACTIONS = "actions"
WORKING = "working"
DONE = "done"
JOBS = "jobs"
STYLE = "style"

# PDF layout + colour, matching lib/template_loader.py. "" is the original
# layout, which ignores colour — so colour is only offered for the others.
LAYOUTS = (("", "original"), ("modern", "modern"), ("executive", "executive"),
           ("sidebar", "sidebar"), ("portfolio", "portfolio"))
COLOURS = ("navy", "slate", "forest", "warm", "classic")
_PREFS = "/jobcontext_prefs.json"  # badge root is writable; /system is not
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
layout_index = 0
colour_index = 0
style_row = 0  # set to the Generate row whenever STYLE is entered
action_index = 0
work_id = 0
message = ""
source = None
_online = False
_last_poll = 0
_prev_buttons = {}
_BUTTONS = ("UP", "DOWN", "A", "B", "C")
_last_input = 0
saving = False  # the contact-card screen saver is up
saver_ok = True  # cleared if the saver ever fails; the app carries on

# Generations you walked away from ("C stop waiting") are still tracked:
# polled in the background from any screen, saver included, and announced
# with a banner when they finish.
_BG_POLL_MS = 15000
_NOTICE_FLASH_MS = 4000
pending = []    # [{"work_id", "what", "company"}]
notices = []    # [(ok, text)] — first one is on screen until a press
_bg_last_poll = 0
_notice_since = 0
_any_prev = False
_bg_failures = 0
_BG_FAILURES_TO_SAY = 4   # ~1 minute of failed checks before saying so


def init():
    global source, _last_input
    ui.init()
    _load_prefs()
    if screensaver.load():
        _saver_guard(screensaver.prepare)
    _last_input = time.ticks_ms()
    source = inputs.best_available()
    _connect()


def _connect():
    """Join WiFi and prove the token works. True when ready to search.

    On failure the app lands on ERROR with the reason, and _online stays
    False so that screen's A retries *this*, not the search screen — Retry
    used to skip straight to SEARCH and look connected when it wasn't.
    """
    global _online
    _online = False
    _draw_splash("connecting...")
    try:
        if not api.connect_wifi(status=lambda text: _draw_splash(text)):
            _go(ERROR, "couldn't join wifi - check WIFI_NETWORKS in secrets.py")
            return False
        api.ping()
    except api.ApiError as exc:
        _go(ERROR, str(exc))
        return False
    _online = True
    return True


def on_exit():
    pass


# ── frame ──────────────────────────────────────────────────────────────────────

def update():
    if _notice_input():
        return
    _background_poll()
    if _screensaver_frame():
        _draw_notice()
        return
    if state == SEARCH:
        _update_search()
    elif state == RESULTS:
        _update_results()
    elif state == JOBS:
        _update_jobs()
    elif state == ACTIONS:
        _update_actions()
    elif state == STYLE:
        _update_style()
    elif state == WORKING:
        _update_working()
    else:
        _update_terminal()
    _draw_notice()
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
    global state, message, _last_input
    state = new_state
    if note:
        message = note
    # A fresh screen gets a full idle period: a generation that took longer
    # than IDLE_SECONDS must not drop straight into the saver over "ready".
    _last_input = time.ticks_ms()
    _rearm()


def _rearm():
    """Treat every button that is down right now as already seen."""
    for name in _BUTTONS:
        _prev_buttons[name] = ui.pressed(name)
    if source is not None:
        source.rearm()


def _screensaver_frame():
    """Run the idle screen saver. True when it owns this frame.

    Any button wakes it, and that press is swallowed: the screens below are
    re-armed so the held button reads as already seen, otherwise waking the
    badge with A would also type a letter or start a generation. WORKING never
    idles into the saver — that screen is polling a job and should say so.
    """
    global _last_input, saving
    now = time.ticks_ms()
    if any(ui.pressed(name) for name in _BUTTONS):
        _last_input = now
        if saving:
            saving = False
            _rearm()
            return True
        return False
    if saving:
        if not _saver_guard(screensaver.draw, now):
            saving = False
            _go(state)  # repaint the real screen under the dead saver
            return False
        return True
    if (state != WORKING and saver_ok and screensaver.enabled()
            and time.ticks_diff(now, _last_input) >= screensaver.idle_ms()):
        if _saver_guard(screensaver.start, now) and _saver_guard(screensaver.draw, now):
            saving = True
            return True
    return False


def _saver_guard(fn, *args):
    """Run a screen saver step; on any failure, turn the saver off.

    The saver is decoration — it must never take the app down with it (on
    hardware a MemoryError while starting it crashed jobcontext to the
    firmware's error screen). The traceback goes to the USB console.
    """
    global saver_ok
    try:
        fn(*args)
        return True
    except Exception as exc:  # noqa: BLE001 — anything here just disables it
        saver_ok = False
        try:
            import sys
            sys.print_exception(exc)
        except AttributeError:  # CPython (host tests) has no print_exception
            print("screensaver disabled:", repr(exc))
        return False


# ── background jobs + notices ──────────────────────────────────────────────────

def _forget(wid):
    for i, job in enumerate(pending):
        if job["work_id"] == wid:
            pending.pop(i)
            return


def _notify(ok, text):
    global _notice_since
    if not notices:
        _notice_since = time.ticks_ms()
    notices.append((ok, text))


def _background_poll():
    """Check one walked-away job every _BG_POLL_MS, from any screen.

    One job per tick and a slow interval: each poll is a blocking HTTPS call
    that freezes the frame (a Tetris hitch), so it should be rare. WORKING
    polls its own job every 2s already and is skipped. A network error just
    waits for the next tick — the job is still running server-side.
    """
    global _bg_last_poll, _bg_failures
    if not pending or state == WORKING:
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, _bg_last_poll) < _BG_POLL_MS:
        return
    _bg_last_poll = now
    job = pending.pop(0)
    pending.append(job)  # round-robin when several are in flight
    try:
        body = api.poll(job["work_id"])
    except api.ApiError as exc:
        # Keep trying — but say so once, rather than leaving the badge
        # silently never announcing a job that finished long ago.
        _bg_failures += 1
        if _bg_failures == _BG_FAILURES_TO_SAY:
            _notify(False, "can't check on your jobs: " + str(exc))
        return
    _bg_failures = 0
    status = body.get("status", "")
    if status == "succeeded":
        _forget(job["work_id"])
        made = ", ".join(body.get("made") or []) or job["what"].lower()
        _notify(True, made + " ready - " + job["company"])
    elif status == "failed":
        _forget(job["work_id"])
        _notify(False, job["what"].lower() + " failed - " + job["company"] + ": "
                + (body.get("detail") or "see the dashboard"))


def _notice_input():
    """A fresh press while a banner is up dismisses it — and only that.

    The press is swallowed (screens re-armed, saver closed) so dismissing a
    banner never also types, searches, or generates. True when swallowed.
    """
    global _any_prev, saving, _last_input, _notice_since
    down = any(ui.pressed(name) for name in _BUTTONS)
    fresh = down and not _any_prev
    _any_prev = down
    if not (fresh and notices):
        return False
    notices.pop(0)
    _notice_since = _last_input = time.ticks_ms()
    saving = False
    _rearm()
    return True


def _draw_notice():
    if not notices:
        return
    ok, text = notices[0]
    lines = ui.wrap(text, ui.WIDTH - 10, 1, 2)
    if len(notices) > 1:
        lines.append("+" + str(len(notices) - 1) + " more - any button")
    h = len(lines) * ui.line_height(1) + 6
    y = ui.HEIGHT - h
    elapsed = time.ticks_diff(time.ticks_ms(), _notice_since)
    flash = elapsed < _NOTICE_FLASH_MS and (elapsed // 250) % 2 == 1
    bg = (20, 90, 50) if ok else (110, 30, 30)
    if flash:
        bg = ui.OK if ok else ui.BAD
    ui.rect(0, y, ui.WIDTH, h, bg)
    for line in lines:
        y += 3
        ui.text(line, 5, y, ui.WHITE, 1)
        y += ui.line_height(1) - 3


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
    global action_index, style_row

    if _edge("UP"):
        action_index = (action_index - 1) % len(MATERIALS)
    if _edge("DOWN"):
        action_index = (action_index + 1) % len(MATERIALS)
    if _edge("C"):
        _go(RESULTS)
        return
    if _edge("A"):
        style_row = len(_style_rows()) - 1  # land on Generate: A, A = go
        _go(STYLE)
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
    ui.footer("U/D choose  A next  C back")


# ── style (layout + colour) ────────────────────────────────────────────────────

def _style_rows():
    """Rows on the style screen; colour is hidden for the original layout."""
    rows = ["layout"]
    if LAYOUTS[layout_index][0]:
        rows.append("colour")
    rows.append("generate")
    return rows


def _update_style():
    global layout_index, colour_index, style_row, work_id

    rows = _style_rows()
    style_row = min(style_row, len(rows) - 1)
    if _edge("UP"):
        style_row = (style_row - 1) % len(rows)
    if _edge("DOWN"):
        style_row = (style_row + 1) % len(rows)
    step = 1 if _edge("A") else (-1 if _edge("B") else 0)
    row = rows[style_row]
    if step and row == "layout":
        layout_index = (layout_index + step) % len(LAYOUTS)
    elif step and row == "colour":
        colour_index = (colour_index + step) % len(COLOURS)
    elif step == 1 and row == "generate":
        hit = results[selected]
        template = LAYOUTS[layout_index][0]
        colour = COLOURS[colour_index]
        _save_prefs()
        _draw_status("queueing " + MATERIALS[action_index][1].lower() + "...")
        try:
            body = api.request_materials(hit["job_id"], MATERIALS[action_index][0], template, colour)
        except api.ApiError as exc:
            _go(ERROR, str(exc))
            return
        work_id = body.get("work_id", 0)
        pending.append({
            "work_id": work_id,
            "what": MATERIALS[action_index][1],
            "company": hit.get("company", ""),
        })
        _go(WORKING)
        return
    if _edge("C"):
        _go(ACTIONS)
        return

    rows = _style_rows()
    ui.clear()
    ui.header(MATERIALS[action_index][1], results[selected].get("company", ""))
    labels = {
        "layout": "Layout: " + LAYOUTS[layout_index][1],
        "colour": "Colour: " + COLOURS[colour_index],
        "generate": "Generate",
    }
    y = 32
    for i, name in enumerate(rows):
        chosen = i == style_row
        if chosen:
            ui.rect(0, y - 2, ui.WIDTH, 16, ui.SELECT)
        ui.text(("> " if chosen else "  ") + labels[name], 6, y, ui.ACCENT if chosen else ui.WHITE, 2)
        y += 18
    hint = "A/B change" if rows[style_row] != "generate" else "A generate"
    ui.footer("U/D row  " + hint + "  C back")


def _load_prefs():
    global layout_index, colour_index
    try:
        with open(_PREFS) as fh:
            prefs = json.loads(fh.read())
    except (OSError, ValueError):
        return
    keys = [key for key, _label in LAYOUTS]
    if prefs.get("template") in keys:
        layout_index = keys.index(prefs["template"])
    if prefs.get("style") in COLOURS:
        colour_index = COLOURS.index(prefs["style"])


def _save_prefs():
    try:
        with open(_PREFS, "w") as fh:
            fh.write(json.dumps({"template": LAYOUTS[layout_index][0], "style": COLOURS[colour_index]}))
    except OSError:
        pass  # a read-only or full filesystem just means the choice isn't remembered


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
        if status in ("succeeded", "failed"):
            _forget(work_id)  # this screen is the notification; no banner too
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

    # Not connected (startup failed, or a request lost the network): A has to
    # actually reconnect. Anything else is a failed action: A goes back to it.
    reconnect = state == ERROR and (not _online or message.startswith("network"))
    if state == DONE:
        ui.footer("A back  C new search")
    else:
        ui.footer(("A reconnect" if reconnect else "A retry") + "  C new search")
    if _edge("C"):
        query = ""
        _go(SEARCH)
    elif _edge("A"):
        if reconnect:
            if _connect():
                _go(RESULTS if results else SEARCH)
            return
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
