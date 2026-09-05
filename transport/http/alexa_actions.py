"""Tenant-scoped, durable Alexa dialogue and confirmed MCP dispatch.

No user-provided domain/function names are dispatched. State and request
receipts live in the tenant DB; confirmed work and its receipt commit together.
"""
from __future__ import annotations

import inspect
import datetime as dt
import json
import math
import re
import time
from typing import get_origin

from lib import config, work
from lib.db import get_connection
from lib.io import _load_json
from lib.user_context import get_current_user_oid, set_user_oid, reset_user_oid
from tools.consolidated import _run, _unwrap_optional, _literal_choices
from transport.http.alexa_catalog import ACTIONS, INTENTS, FIXED, fields

TTL = 300
PAGE_SIZE = 650
MAX_RESULT = 18000
KIND = "alexa.action"
CONTROL_INTENTS = {"AnswerIntent", "NumberAnswerIntent", "DateAnswerIntent", "ChangeFieldIntent", "RunActionIntent", "ActionStatusIntent",
                   "MoreResultIntent", "ActionCatalogIntent", "AMAZON.YesIntent", "AMAZON.NoIntent"}


def plain(value):
    text = str(value)
    text = re.sub(r"```.*?```", " [Code is available in your workspace.] ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "[link in workspace]", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[═─│┌┐└┘├┤┬┴┼■●#*`]+", " ", text)
    text = " ".join(text.split())
    return text if len(text) <= MAX_RESULT else text[:MAX_RESULT] + " The rest is available in your workspace."


def reply(text, *, title="jobContext", listen=True):
    return {"title": title, "summary": text, "speech": text, "rows": [], "listen": listen}


def _coerce(name, value, param):
    value = value.strip()
    if not value or len(value) > 1500:
        raise ValueError("Please give a short, nonempty answer.")
    target = _unwrap_optional(param.annotation)
    choices = _literal_choices(param.annotation)
    if choices:
        match = next((c for c in choices if str(c).replace("_", " ").casefold() == value.casefold()), None)
        if match is None:
            raise ValueError("Choose " + ", ".join(map(str, choices)) + ".")
        return match
    if target is bool:
        if value.casefold() not in {"true", "false", "yes", "no"}:
            raise ValueError("Say yes or no.")
        return value.casefold() in {"true", "yes"}
    if target in (int, float):
        try:
            number = target(value)
        except ValueError:
            raise ValueError("Please give a number using digits.") from None
        if not math.isfinite(number) or abs(number) > 100000000:
            raise ValueError("That number is outside the supported range.")
        if name in {"limit", "num_results", "days", "days_ahead"} and not 1 <= number <= 50:
            raise ValueError("Choose a number from 1 to 50.")
        return number
    if get_origin(target) is list:
        return [part.strip() for part in value.split(",") if part.strip()]
    if target is not str:
        raise ValueError("That field needs the dashboard.")
    if name in {"date", "interview_date", "posted_date", "week_ending", "since"}:
        try:
            return dt.date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("Give a complete date. Say: the date is, followed by the day, month and year.") from None
    return value


def _slot(req, name):
    intent = req.get("intent") or {}
    slots = intent.get("slots") or {}
    if name == "Answer":
        typed = {"NumberAnswerIntent": "NumberAnswer", "DateAnswerIntent": "DateAnswer"}.get(intent.get("name"))
        slot = slots.get(typed) or slots.get(name) or {}
    else:
        slot = slots.get(name) or {}
    if name == "Field":
        for authority in (slot.get("resolutions") or {}).get("resolutionsPerAuthority", []):
            if authority.get("status", {}).get("code") == "ER_SUCCESS_MATCH":
                values = authority.get("values", [])
                if len(values) == 1:
                    return values[0]["value"].get("id", "")
    return str(slot.get("value") or "").strip()


def _question(action, state):
    name = state["field"]
    param = fields(action)[name]
    hint = " Separate items with commas." if get_origin(_unwrap_optional(param.annotation)) is list else ""
    choices = _literal_choices(param.annotation)
    if choices:
        hint += " Choose " + ", ".join(map(str, choices)) + "."
    carrier = "my answer is"
    if _unwrap_optional(param.annotation) in (int, float):
        carrier = "the number is"
    if name in {"date", "interview_date", "posted_date", "week_ending", "since"}:
        carrier = "the date is"
    return reply(f"What is the {name.replace('_', ' ')}?{hint} Say: {carrier}, followed by your answer.", title=action.phrase)


def _ready(action, state, con):
    missing = [name for name, p in fields(action).items()
               if p.default is inspect.Parameter.empty and name not in state["params"]]
    if missing:
        state["phase"], state["field"] = "collect", missing[0]
        return _question(action, state)
    state["phase"] = "ready"
    if action.key in {"job_search.result", "job_search.queue_result"}:
        from transport.http.alexa_jobs import selected_job, detail_view
        try:
            job = selected_job(con, state)
        except ValueError as exc:
            state.pop("phase", None)
            return reply(str(exc))
        number = state["params"]["result_number"]
        if action.key == "job_search.result":
            state.pop("action", None)
            return detail_view(job, number)
        return reply(f"Add job {number}, {job['role']} at {job['company']}, {job['location'] or 'location not listed'}, to your evaluation queue with its saved job description? Say yes to confirm, or cancel. This does not submit an application.", title="Queue this job?")
    details = "; ".join(f"{k.replace('_', ' ')}: {str(v)}" for k, v in state["params"].items())
    # Never silently truncate a confirmation. Long dictation must be shortened.
    if len(details) > 3500:
        return reply("This request is too long to read back. Change a field to shorten it, or cancel and use the dashboard.")
    suffix = "Say yes to confirm" if action.mode == "confirm" else "Say run it"
    return reply(f"{action.phrase.capitalize()}. {details or 'Using the default settings'}. {suffix}, or say change followed by a field name.", title=action.phrase)


def _inputs(action, state, con):
    params = dict(state["params"])
    allowed = fields(action)
    if set(params) - set(allowed):
        raise ValueError("This request contains an unsupported field. Please start again.")
    if "search_id" in action.parameters:
        from transport.http.alexa_jobs import selected_job
        selected_job(con, state)
        params["search_id"] = state["search_id"]
    # Required JDs are selected exactly from saved queue records, never guessed
    # or dictated. Company + role must match uniquely before confirmation.
    if "job_description" in action.parameters and action.parameters["job_description"].default is inspect.Parameter.empty:
        jobs = _load_json(config.JOB_QUEUE_FILE, {"jobs": []}).get("jobs", [])
        matches = [j for j in jobs if str(j.get("company", "")).casefold() == str(params.get("company", "")).casefold()
                   and str(j.get("role", "")).casefold() == str(params.get("role", "")).casefold()]
        if len(matches) != 1 or not matches[0].get("jd"):
            raise ValueError("I need one saved job description matching that company and role. Add it to your job queue in the dashboard, then try again.")
        params["job_description"] = matches[0]["jd"]
    params.update(FIXED.get(action.key, {}))
    return {"key": action.key, "params": params, "oid": get_current_user_oid()}


def execute(inputs):
    """Control-plane executor; partition context comes from the work row."""
    action = ACTIONS.get(inputs.get("key"))
    if action is None or action.mode == "handoff":
        raise ValueError("Action is not enabled for Alexa")
    params = dict(inputs["params"])
    params.update(FIXED.get(action.key, {}))
    domain, name = action.key.split(".")
    # Avoid creating a second asynchronous job whose status would hide the result.
    name = {"submit_resume": "generate_resume", "submit_cover_letter": "generate_cover_letter"}.get(name, name) if domain == "documents" else name
    # Oura also keys its records by OID. Worker partition routing alone is
    # insufficient; persist the verified identity, never an Alexa slot value.
    token = set_user_oid(inputs.get("oid", ""))
    try:
        result = _run(domain, name, params)
    finally:
        reset_user_oid(token)
    artifact = {"text": plain(result), "title": action.phrase}
    if action.key == "job_search.discover":
        artifact["job_search"] = json.loads(result)
    return artifact


work.register_kind(KIND, execute)


def _result(con, state, more=False):
    item_id = state.get("last_work")
    row = con.execute("SELECT status, artifacts_json FROM work_items WHERE id=? AND kind=?", (item_id, KIND)).fetchone()
    if not row:
        return reply("There is no recent Alexa request in this session. Start an action first.")
    if row["status"] != "succeeded":
        return reply(f"Request {item_id} is {row['status']}." + (" Check the dashboard for details." if row["status"] == "failed" else " Say check my last request in a moment."), listen=False)
    artifact = json.loads(row["artifacts_json"] or "{}")
    if "job_search" in artifact:
        from transport.http.alexa_jobs import search_view
        from tools.job_discovery import lookup_result
        if artifact["job_search"].get("results"):
            try:
                lookup_result(artifact["job_search"].get("search_id"), 1, con)
            except ValueError as exc:
                state["search_id"] = None
                return reply(str(exc))
        return search_view(artifact["job_search"], state, more)
    text = artifact.get("text") or "The action returned no content. Check your workspace."
    offset = state.get("offset", 0) if more else 0
    # Cut only at a word boundary; every page can be read by voice-only users.
    end = min(len(text), offset + PAGE_SIZE)
    if end < len(text):
        boundary = text.rfind(" ", offset, end)
        end = boundary if boundary > offset else end
    page = text[offset:end].strip()
    state["offset"] = end
    if end < len(text):
        page += " Say read more for the next page."
    return reply(page or "That is the end of the result.", title=artifact.get("title", "Result"))


def _turn(con, state, req):
    intent = req.get("intent", {}).get("name", "")
    if intent in INTENTS or intent in {"ActionCatalogIntent", "ActionStatusIntent", "MoreResultIntent"}:
        # A different request must not leave an older write waiting for "yes".
        for key in ("action", "phase", "field", "params"):
            state.pop(key, None)
    if intent in {"AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NoIntent"}:
        state.pop("action", None)
        state.pop("phase", None)
        return reply("Cancelled. No new action will be submitted.", listen=False), None
    if intent == "ActionCatalogIntent":
        return reply("You can search jobs, prepare interviews, manage contacts and stories, generate documents, record updates, review wellbeing, and prepare certification reports. Try: prepare for an interview. For a pending request, say change followed by a field name, or cancel."), None
    if intent in {"ActionStatusIntent", "MoreResultIntent"}:
        if not state.get("last_work"):
            last = con.execute("SELECT id FROM work_items WHERE kind=? ORDER BY id DESC LIMIT 1", (KIND,)).fetchone()
            if last:
                state["last_work"] = last["id"]
        return _result(con, state, intent == "MoreResultIntent"), None
    if intent in INTENTS:
        action = INTENTS[intent]
        if action.mode == "handoff":
            return reply(action.reason, title=action.phrase, listen=False), None
        state.update(action=action.key, params={}, phase="collect")
        if action.key == "job_search.discover":
            state["search_id"] = None
            value = _slot(req, "JobQuery")
            if value:
                state["params"]["query"] = value
        if action.key in {"job_search.result", "job_search.queue_result"}:
            number = _slot(req, "JobNumber")
            if number:
                try:
                    state["params"]["result_number"] = int(number)
                except ValueError:
                    return reply("Please choose a job using its number."), None
        return _ready(action, state, con), None
    action = ACTIONS.get(state.get("action"))
    if not action:
        return reply("There is no pending action. Ask for an action first, such as search for jobs."), None
    if intent == "ChangeFieldIntent":
        name = _slot(req, "Field").replace(" ", "_").lower()
        if name not in fields(action):
            return reply("That field is not available. Available fields are: " + ", ".join(fields(action)).replace("_", " ") + "."), None
        state.update(phase="collect", field=name)
        return _question(action, state), None
    if intent in {"AnswerIntent", "NumberAnswerIntent", "DateAnswerIntent"} and state.get("phase") == "collect":
        name = state["field"]
        try:
            state["params"][name] = _coerce(name, _slot(req, "Answer"), fields(action)[name])
        except ValueError as exc:
            return reply(str(exc) + " Say: my answer is, followed by the value."), None
        return _ready(action, state, con), None
    if intent in {"AMAZON.YesIntent", "RunActionIntent"} and state.get("phase") == "ready":
        if action.mode == "confirm" and intent != "AMAZON.YesIntent":
            return _ready(action, state, con), None
        details = "; ".join(f"{k.replace('_', ' ')}: {str(v)}" for k, v in state["params"].items())
        if len(details) > 3500:
            return _ready(action, state, con), None
        try:
            inputs = _inputs(action, state, con)
        except ValueError as exc:
            return reply(str(exc)), None
        item_id = work.enqueue_in_transaction(con, KIND, inputs, origin="alexa")
        state.update(last_work=item_id, offset=0)
        state.pop("action", None)
        state.pop("phase", None)
        return reply(f"Request {item_id} is queued. Say: Alexa, ask job context to check my last request.", listen=False), item_id
    return _ready(action, state, con), None


def clear_pending(payload):
    """Switching to a fast view abandons any prior guided confirmation."""
    session = (payload.get("session") or {}).get("sessionId")
    if not session:
        return
    with get_connection() as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='alexa_dialogues'").fetchone():
            con.execute("DELETE FROM alexa_dialogues WHERE session_id=?", (session,))


def handle(payload):
    """Called only after signature verification and account/tenant resolution."""
    req = payload["request"]
    request_id = str(req.get("requestId") or "")
    session_id = str((payload.get("session") or {}).get("sessionId") or "")
    device_id = str((((payload.get("context") or {}).get("System") or {}).get("device") or {}).get("deviceId") or "")
    touch = req.get("type") == "Alexa.Presentation.APL.UserEvent"
    if touch and device_id:
        session_id = "display:" + device_id
    if not request_id or not session_id:
        return reply("Please launch job context again to start a session.", listen=False)
    now = time.time()
    work.prepare_transactional_enqueue()
    with get_connection() as con:
        con.execute("CREATE TABLE IF NOT EXISTS alexa_dialogues (session_id TEXT PRIMARY KEY, state TEXT NOT NULL, expires REAL NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS alexa_receipts (request_id TEXT PRIMARY KEY, response TEXT NOT NULL, expires REAL NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS alexa_job_devices (device_id TEXT PRIMARY KEY, search_id TEXT, expires REAL NOT NULL)")
        con.commit()
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM alexa_dialogues WHERE expires < ?", (now,))
        con.execute("DELETE FROM alexa_receipts WHERE expires < ?", (now,))
        receipt = con.execute("SELECT response FROM alexa_receipts WHERE request_id=?", (request_id,)).fetchone()
        if receipt:
            return json.loads(receipt["response"])
        row = con.execute("SELECT state FROM alexa_dialogues WHERE session_id=?", (session_id,)).fetchone()
        state = json.loads(row["state"]) if row else {}
        if device_id:
            state["device_id"] = device_id
        if "search_id" not in state and device_id:
            device = con.execute("SELECT search_id FROM alexa_job_devices WHERE device_id=? AND expires>=?", (device_id, now)).fetchone()
            if device:
                state["search_id"] = device["search_id"]
        if touch:
            # A tap invalidates any voice confirmation on this same device.
            con.execute("DELETE FROM alexa_dialogues WHERE json_extract(state, '$.device_id')=?", (device_id,))
            response, item_id = _touch(con, state, req), None
        else:
            response, item_id = _turn(con, state, req)
        if device_id and "search_id" in state:
            con.execute("INSERT OR REPLACE INTO alexa_job_devices VALUES (?,?,?)", (device_id, state["search_id"], now + 3600))
        con.execute("INSERT OR REPLACE INTO alexa_dialogues VALUES (?, ?, ?)", (session_id, json.dumps(state), now + TTL))
        con.execute("INSERT INTO alexa_receipts VALUES (?, ?, ?)", (request_id, json.dumps(response), now + 600))
    if item_id is not None:
        work.notify_committed(item_id)
    return response


def _touch(con, state, req):
    from tools.job_discovery import lookup_result
    from transport.http.alexa_jobs import detail_view
    for key in ("action", "phase", "field", "params"):
        state.pop(key, None)
    args = req.get("arguments") or []
    if len(args) != 3 or args[0] != "job_detail" or req.get("token") != "jobcontext-search-" + str(args[1]):
        return reply("That job selection is unavailable. Ask for your search results again.")
    try:
        if isinstance(args[2], bool) or not re.fullmatch(r"[0-9]{1,2}", str(args[2])):
            raise ValueError("Choose a valid job number.")
        number = int(args[2])
        job = lookup_result(str(args[1]), number, con)
    except (ValueError, TypeError) as exc:
        return reply(str(exc))
    state["search_id"] = str(args[1])
    return detail_view(job, number)
