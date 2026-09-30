import json

import pytest

from lib import work, config
from lib.io import _load_json
from tools import job_discovery as jd
from transport.http import alexa_actions as aa
from transport.http.alexa_catalog import ACTIONS
from transport.http.alexa_views import render_directive
from tests.test_alexa_actions import payload
from tests.test_job_discovery import job


def say(intent, value=None, slot="Answer", session="s1"):
    request = payload(intent, value, slot, session=session)
    request["context"] = {"System": {"device": {"deviceId": "show-one"}}}
    return aa.handle(request)


@pytest.fixture
def results(isolated_server, monkeypatch):
    jd.save_board("ashby", "acme")
    async def fetch(boards):
        return [([job(f"Engineer {n}", source=f"https://example.com/{n}") for n in range(1, 6)], None)]
    monkeypatch.setattr(jd, "_fetch_all", fetch)
    response = say(ACTIONS["job_search.discover"].intent, "engineer", "JobQuery")
    assert "run it" in response["speech"]
    say("RunActionIntent")
    item = work.list_items()[0]
    work._execute(None, item["id"])
    response = say("ActionStatusIntent")
    assert len(response["rows"]) == 5
    return response


def test_search_details_confirm_and_replay(results):
    assert "Job 1" in results["speech"] and "Job 4" not in results["speech"]
    assert "Job 4" in say("MoreResultIntent")["speech"]
    detail = say(ACTIONS["job_search.result"].intent, "2", "JobNumber")
    assert "Engineer 2" in detail["speech"] and "Python" in detail["speech"]
    review = say(ACTIONS["job_search.queue_result"].intent, "2", "JobNumber")
    assert "Engineer 2" in review["speech"] and "yes to confirm" in review["speech"]
    assert len(work.list_items()) == 1
    assert "yes to confirm" in say("RunActionIntent")["speech"]
    confirmation = payload("AMAZON.YesIntent")
    ack = aa.handle(confirmation)
    assert aa.handle(confirmation) == ack
    assert len(work.list_items()) == 2
    item = work.list_items()[0]
    work._execute(None, item["id"])
    assert "Queued:" in say("ActionStatusIntent")["speech"]
    queued = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"]
    assert len(queued) == 1 and queued[0]["role"] == "Engineer 2"


def test_cancel_no_selection_and_invalid_number(results):
    say(ACTIONS["job_search.queue_result"].intent, "2", "JobNumber")
    say("AMAZON.NoIntent")
    say("AMAZON.YesIntent")
    assert len(work.list_items()) == 1
    assert "Choose" in say(ACTIONS["job_search.result"].intent, "99", "JobNumber")["speech"]
    assert "number" in say(ACTIONS["job_search.result"].intent, "garbage", "JobNumber")["speech"]
    assert "result number" in say(ACTIONS["job_search.result"].intent)["speech"]
    assert "Engineer 1" in say("NumberAnswerIntent", "1", "NumberAnswer")["speech"]


def test_new_session_restores_device_search_and_expiry_blocks_yes(results, monkeypatch):
    assert "Engineer 3" in say(ACTIONS["job_search.queue_result"].intent, "3", "JobNumber", session="new")["speech"]
    now = jd.time.time()
    monkeypatch.setattr(jd.time, "time", lambda: now + jd.TTL + 1)
    say("AMAZON.YesIntent", session="new")
    assert len(work.list_items()) == 1
    assert "expired" in say("ActionStatusIntent")["speech"]


def test_other_device_cannot_accidentally_select_this_devices_results(results):
    request = payload(ACTIONS["job_search.queue_result"].intent, "1", "JobNumber", session="another")
    request["context"] = {"System": {"device": {"deviceId": "other-echo"}}}
    assert "unavailable" in aa.handle(request)["speech"]


def touch(search_id, number=2, token=None):
    p = payload("unused", session="")
    p["request"].update(type="Alexa.Presentation.APL.UserEvent", arguments=["job_detail", search_id, number], token=token or "jobcontext-search-" + search_id)
    p["context"] = {"System": {"device": {"deviceId": "show-one"}}}
    return p


def test_touch_is_read_only_clears_prior_confirmation_and_binds_followup(results):
    say(ACTIONS["job_search.queue_result"].intent, "1", "JobNumber")
    detail = aa.handle(touch(results["search_id"]))
    assert "Engineer 2" in detail["speech"]
    say("AMAZON.YesIntent")
    assert len(work.list_items()) == 1
    assert "Engineer 2" in say(ACTIONS["job_search.queue_result"].intent, "2", "JobNumber", session="voice-after-touch")["speech"]
    invalid = aa.handle(touch(results["search_id"], token="different-screen"))
    assert "unavailable" in invalid["speech"]
    assert len(work.list_items()) == 1


def test_apl_rows_use_only_safe_selection_arguments(results):
    results["rows"][0]["primary"] = "<b>Company</b>"
    directive = render_directive(results)
    assert directive["token"] == "jobcontext-search-" + results["search_id"]
    assert directive["datasources"]["view"]["rows"][0]["primary"] == "&lt;b&gt;Company&lt;/b&gt;"
    document = json.dumps(directive["document"])
    assert "TouchWrapper" in document and "job_detail" in document
    assert "https://" not in document and "queue_result" not in document


def test_new_search_invalidates_old_selection(results):
    say(ACTIONS["job_search.discover"].intent, "different role", "JobQuery")
    response = say(ACTIONS["job_search.queue_result"].intent, "1", "JobNumber", session="new-session")
    assert "unavailable" in response["speech"]
    assert len(work.list_items()) == 1


@pytest.mark.parametrize("number", [True, 1.5, "bad", 99])
def test_bad_touch_number_cannot_submit(results, number):
    response = aa.handle(touch(results["search_id"], number))
    assert "Choose" in response["speech"]
    assert len(work.list_items()) == 1
