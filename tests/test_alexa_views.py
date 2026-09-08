"""Voice/display adapters: bounded summaries, markup safety, and data policy."""
import datetime as dt

import pytest

from lib import config
from lib.io import _save_json
from transport.http.alexa_views import build_view, render_directive


def test_pipeline_uses_digest_active_policy_and_bounds_speech(isolated_server):
    today = dt.date.today().isoformat()
    records = [{"company": f"Company {n}", "role": "Engineer", "status": "applied",
                "last_updated": today, "notes": "PRIVATE NOTES"} for n in range(12)]
    records += [{"company": "Closed", "status": "rejected", "last_updated": today},
                {"company": "Stale", "status": "applied", "last_updated": "2020-01-01"}]
    _save_json(config.STATUS_FILE, {"applications": records})
    view = build_view("pipeline")
    assert view["summary"] == "12 active applications. 12 waiting on a response."
    assert len(view["rows"]) == 10
    assert "Company 2" in view["speech"] and "Company 3" not in view["speech"]
    assert "PRIVATE NOTES" not in str(view)
    assert "first 10" in view["footer"]


def test_interviews_are_sorted_and_limited_to_fourteen_days(isolated_server):
    today = dt.date.today()
    _save_json(config.INTERVIEWS_FILE, {"interviews": [
        {"company": name, "role": "Engineer", "interview_date": day,
         "interview_type": "hiring_manager", "interviewer": "Private Contact"}
        for name, day in [("Later", (today + dt.timedelta(days=14)).isoformat()),
                          ("Today", today.isoformat()), ("Broken", "not-a-date"),
                          ("Past", (today - dt.timedelta(days=1)).isoformat()),
                          ("Far away", (today + dt.timedelta(days=15)).isoformat())]
    ]})
    view = build_view("interviews")
    assert [r["primary"] for r in view["rows"]] == ["Today", "Later"]
    assert "hiring manager" in view["speech"]
    assert "Private Contact" not in str(view)


@pytest.mark.parametrize("action", ["pipeline", "interviews"])
def test_empty_views_have_spoken_and_visible_explanation(isolated_server, action):
    view = build_view(action)
    assert view["speech"] == view["summary"]
    assert view["rows"] == []


def test_display_escapes_workspace_markup_without_interpolating_document():
    text = '<b>Acme & Co</b> ${viewport.width}'
    directive = render_directive({"title": "Pipeline", "summary": text,
                                  "rows": [{"primary": text, "secondary": "", "detail": ""}]})
    assert text not in str(directive["document"])
    assert directive["datasources"]["view"]["summary"] == '&lt;b&gt;Acme &amp; Co&lt;/b&gt; ${viewport.width}'
    assert directive["document"]["version"] == "1.0"


def test_unknown_view_does_not_dispatch_tools():
    with pytest.raises(ValueError, match="Unsupported"):
        build_view("delete")
