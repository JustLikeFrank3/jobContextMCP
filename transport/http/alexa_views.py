"""Read-only voice/display adapters over the same workspace data as MCP tools."""
from __future__ import annotations

import datetime as dt
from html import escape

from lib import config
from lib.io import _load_json
from tools import digest


def _text(value, limit: int = 160) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_view(action: str) -> dict:
    """Caller must establish the linked user's tenant context before calling."""
    if action == "briefing":
        speech = digest.get_voice_briefing()
        return {"title": "Your briefing", "summary": speech, "speech": speech, "rows": []}
    if action == "pipeline":
        # Match the voice digest's active/stale policy; omit private notes,
        # contact details and wellbeing nudges from a shared-room display.
        active = [a for a in digest._load_apps() if not digest._is_closed(a)
                  and (digest._days_since(a.get("last_updated", "")) < 60
                       or a.get("next_steps"))]
        waiting = sum(digest._is_waiting(a) for a in active)
        summary = (f"{len(active)} active applications. {waiting} waiting on a response."
                   if active else "Your pipeline is empty right now.")
        rows = [{"primary": _text(a.get("company", "Unknown company")),
                 "secondary": _text(a.get("role")),
                 "detail": _text(a.get("status"))} for a in active[:10]]
        speech = summary
        if rows:
            speech += " " + " ".join(
                f"{r['primary']}: {r['detail']}." for r in rows[:3])
        if len(active) > 3:
            speech += " Open your dashboard for the rest."
        return {"title": "Application pipeline", "summary": summary,
                "speech": speech, "rows": rows,
                "footer": "Showing the first 10 applications" if len(active) > 10 else ""}
    if action != "interviews":
        raise ValueError("Unsupported Alexa view")
    today = dt.date.today()
    upper = today + dt.timedelta(days=14)
    upcoming = []
    for record in _load_json(config.INTERVIEWS_FILE, {"interviews": []}).get("interviews", []):
        try:
            day = dt.date.fromisoformat(str(record.get("interview_date") or "")[:10])
        except ValueError:
            continue
        if today <= day <= upper:
            upcoming.append((day, record))
    upcoming.sort(key=lambda item: item[0])
    rows = [{"primary": _text(r.get("company", "Unknown company")),
             "secondary": _text(r.get("role")),
             "detail": f"{day.strftime('%A, %B')} {day.day} · "
                       + _text(r.get("interview_type", "interview")).replace("_", " ")}
            for day, r in upcoming[:10]]
    summary = (f"{len(upcoming)} interviews in the next 14 days." if upcoming
               else "No interviews scheduled in the next 14 days.")
    speech = summary
    if rows:
        speech += " " + " ".join(f"{r['primary']}, {r['detail']}." for r in rows[:3])
    if len(upcoming) > 3:
        speech += " Open your dashboard for the rest."
    return {"title": "Upcoming interviews", "summary": summary,
            "speech": speech, "rows": rows,
            "footer": "Showing the first 10 interviews" if len(upcoming) > 10 else ""}


def render_directive(view: dict) -> dict:
    """APL 1.0 core components: no external images, packages or network reads.

    Data is kept outside the document expressions and escaped for Text markup.
    Scrollable content supports smaller Show viewports without truncating rows.
    """
    data = {key: escape(str(view.get(key, ""))) for key in ("title", "summary", "footer")}
    data["rows"] = [{key: escape(value) for key, value in row.items()}
                    for row in view["rows"]]
    return {
        "type": "Alexa.Presentation.APL.RenderDocument",
        "token": "jobcontext-view",
        "document": {
            "type": "APL", "version": "1.0", "theme": "dark",
            "mainTemplate": {"parameters": ["payload"], "items": [{
                "type": "Container", "width": "100%", "height": "100%",
                "paddingLeft": "5vw", "paddingRight": "5vw",
                "paddingTop": "4vh", "paddingBottom": "4vh",
                "items": [
                    {"type": "Text", "text": "jobContext", "color": "#56D6DE", "fontSize": "24dp"},
                    {"type": "Text", "text": "${payload.view.title}", "color": "#FFFFFF",
                     "fontSize": "${viewport.width >= 960 ? 48 : 32}", "maxLines": 2},
                    {"type": "ScrollView", "width": "100%", "grow": 1, "shrink": 1,
                     "item": {"type": "Container", "width": "100%", "items": [
                         {"type": "Text", "width": "100%", "text": "${payload.view.summary}",
                          "color": "#E6EDF7", "fontSize": "${viewport.width >= 960 ? 32 : 26}", "spacing": "16dp"},
                         {"type": "Container", "width": "100%", "data": "${payload.view.rows}", "items": [{
                             "type": "Container", "width": "100%", "spacing": "20dp", "items": [
                                 {"type": "Text", "width": "100%", "text": "${data.primary}", "color": "#56D6DE", "fontSize": "${viewport.width >= 960 ? 36 : 28}"},
                                 {"type": "Text", "width": "100%", "text": "${data.secondary}", "color": "#FFFFFF", "fontSize": "${viewport.width >= 960 ? 28 : 24}"},
                                 {"type": "Text", "width": "100%", "text": "${data.detail}", "color": "#CAD4E2", "fontSize": "${viewport.width >= 960 ? 26 : 22}"}
                             ]}]},
                         {"type": "Text", "text": "${payload.view.footer}", "fontSize": "20dp", "color": "#CAD4E2"}
                     ]}},
                    {"type": "Text", "text": "Try: Alexa, show my pipeline · upcoming interviews",
                     "color": "#CAD4E2", "fontSize": "18dp", "maxLines": 2}
                ]
            }]}
        },
        "datasources": {"view": data}
    }
