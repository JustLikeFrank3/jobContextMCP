"""Real tenant DB tests for transport policy, confirmation, replay and jobs."""
import inspect
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from lib import config, work
from lib.db import get_connection
from lib.io import _save_json
from lib.user_context import set_data_folder, reset_data_folder
from tools.consolidated import DOMAINS
from transport.http import alexa_actions as aa
from transport.http.alexa_catalog import ACTIONS, INTENTS, FIXED, fields, model


def payload(intent, value=None, slot="Answer", session="s1", request_id=None):
    return {"session": {"sessionId": session}, "request": {
        "requestId": request_id or str(uuid.uuid4()), "type": "IntentRequest",
        "intent": {"name": intent, "slots": {slot: {"value": value}} if value is not None else {}}}}


def begin(key):
    return aa.handle(payload(ACTIONS[key].intent))


def answer(value):
    return aa.handle(payload("AnswerIntent", value))


def test_every_mcp_action_has_reviewed_policy_and_utterance():
    assert set(ACTIONS) == {f"{d}.{a}" for d, actions in DOMAINS.items() for a in actions}
    assert len(INTENTS) == len(ACTIONS)
    assert len({a.phrase for a in ACTIONS.values()}) == len(ACTIONS)
    for action in ACTIONS.values():
        assert action.mode in {"read", "confirm", "handoff"}
        if action.mode != "handoff":
            for name, p in action.parameters.items():
                if p.default is inspect.Parameter.empty:
                    assert name in fields(action) or name == "job_description", action.key


def test_generated_model_covers_dispatch_and_search_query_rules():
    lm = model()["interactionModel"]["languageModel"]
    names = [i["name"] for i in lm["intents"]]
    assert len(names) == len(set(names))
    assert set(INTENTS) <= set(names)
    for intent in lm["intents"]:
        if any(s["type"] == "AMAZON.SearchQuery" for s in intent.get("slots", [])):
            assert all(sample.count("{") == 1 and not sample.startswith("{") for sample in intent["samples"])


@pytest.mark.parametrize("key", [key for key, a in ACTIONS.items() if a.mode == "handoff"])
def test_handoff_never_enqueues(isolated_server, key):
    result = begin(key)
    assert "dashboard" in result["speech"]
    assert work.list_items() == []


def test_confirmed_update_is_atomic_and_replay_safe(isolated_server):
    assert "company" in begin("applications.update")["speech"]
    answer("Acme")
    answer("Engineer")
    result = answer("applied")
    assert "Acme" in result["speech"] and "yes to confirm" in result["speech"]
    assert not work.list_items()
    assert "yes to confirm" in aa.handle(payload("RunActionIntent"))["speech"]
    confirmation = payload("AMAZON.YesIntent")
    response = aa.handle(confirmation)
    assert aa.handle(confirmation) == response
    aa.handle(payload("AMAZON.YesIntent"))
    items = work.list_items()
    assert len(items) == 1
    assert items[0]["inputs"] == {"key": "applications.update", "params": {"company": "Acme", "role": "Engineer", "status": "applied"}, "oid": ""}
    assert items[0]["max_attempts"] == 1


def test_cancel_and_expiry_cannot_execute(isolated_server, monkeypatch):
    begin("materials.reindex")
    aa.handle(payload("AMAZON.NoIntent"))
    aa.handle(payload("AMAZON.YesIntent"))
    begin("materials.reindex")
    now = aa.time.time()
    monkeypatch.setattr(aa.time, "time", lambda: now + aa.TTL + 1)
    assert "no pending" in aa.handle(payload("AMAZON.YesIntent"))["speech"]
    assert work.list_items() == []


def test_optional_parameters_cannot_turn_read_into_write(isolated_server):
    begin("job_search.web")
    answer("engineering jobs")
    assert "not available" in aa.handle(payload("ChangeFieldIntent", "auto queue", "Field"))["speech"]
    aa.handle(payload("ChangeFieldIntent", "num results", "Field"))
    assert "from 1 to 50" in answer("100")["speech"]
    answer("3")
    aa.handle(payload("RunActionIntent"))
    params = work.list_items()[0]["inputs"]["params"]
    assert params["auto_queue"] is False and params["num_results"] == 3


def test_types_and_literal_validation():
    boolean = inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=bool)
    assert aa._coerce("x", "false", boolean) is False
    with pytest.raises(ValueError):
        aa._coerce("x", "maybe", boolean)
    param = ACTIONS["certification.export"].parameters["format"]
    assert aa._coerce("format", "portal text", param) == "portal_text"
    with pytest.raises(ValueError):
        aa._coerce("format", "exe", param)


def test_saved_jd_requires_unique_exact_company_and_role(isolated_server):
    begin("documents.generate_resume")
    answer("Acme")
    answer("Engineer")
    assert "saved job description" in aa.handle(payload("AMAZON.YesIntent"))["speech"]
    _save_json(config.JOB_QUEUE_FILE, {"jobs": [{"company": "Acme", "role": "Engineer", "jd": "Exact saved description"}]})
    aa.handle(payload("AMAZON.YesIntent"))
    assert work.list_items()[0]["inputs"]["params"]["job_description"] == "Exact saved description"


def test_failed_transaction_rolls_back_confirmation_and_queue(isolated_server, monkeypatch):
    begin("materials.reindex")
    original = work.enqueue_in_transaction
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("crash before commit")
    monkeypatch.setattr(work, "enqueue_in_transaction", crash)
    confirmation = payload("AMAZON.YesIntent")
    with pytest.raises(RuntimeError):
        aa.handle(confirmation)
    assert work.list_items() == []
    monkeypatch.setattr(work, "enqueue_in_transaction", original)
    aa.handle(confirmation)
    assert len(work.list_items()) == 1


def test_executor_uses_shared_mcp_dispatch_and_no_hidden_writes(monkeypatch):
    calls = []
    monkeypatch.setattr(aa, "_run", lambda *args: calls.append(args) or "**Found jobs**")
    result = aa.execute({"key": "job_search.web", "params": {"query": "engineer", "auto_queue": True}})
    assert calls == [("job_search", "web", {"query": "engineer", "auto_queue": False})]
    assert result["text"] == "Found jobs"
    with pytest.raises(ValueError):
        aa.execute({"key": "workspace.setup", "params": {}})


def test_tenant_isolation_and_concurrent_duplicate_confirmation(isolated_server, tmp_path):
    partition = tmp_path / "alice"
    tok = set_data_folder(partition)
    try:
        begin("materials.reindex")
    finally:
        reset_data_folder(tok)
    confirmation = payload("AMAZON.YesIntent")
    def invoke():
        token = set_data_folder(partition)
        try:
            return aa.handle(confirmation)
        finally:
            reset_data_folder(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: invoke(), range(2)))
    assert responses[0] == responses[1]
    token = set_data_folder(partition)
    try:
        assert len(work.list_items()) == 1
    finally:
        reset_data_folder(token)
    token = set_data_folder(tmp_path / "bob")
    try:
        assert "no pending" in aa.handle(confirmation)["speech"]
        assert work.list_items() == []
    finally:
        reset_data_folder(token)


def test_result_pages_and_new_session_status(isolated_server):
    begin("materials.list")
    aa.handle(payload("RunActionIntent"))
    item = work.list_items()[0]
    text = "First " + "middle " * 150 + "Last"
    with get_connection() as con:
        con.execute("UPDATE work_items SET status='succeeded', artifacts_json=? WHERE id=?", (json.dumps({"text": text, "title": "Documents"}), item["id"]))
    first = aa.handle(payload("ActionStatusIntent", session="new"))
    second = aa.handle(payload("MoreResultIntent", session="new"))
    assert first["speech"].startswith("First") and "read more" in first["speech"]
    assert second["speech"].endswith("Last")


def test_long_confirmation_does_not_silently_omit_values(isolated_server):
    begin("people.log")
    for value in ["a" * 1000, "b" * 1000, "c" * 1000, "d" * 1000]:
        result = answer(value)
    assert "too long" in result["speech"]
    aa.handle(payload("AMAZON.YesIntent"))
    assert work.list_items() == []


def test_worker_execution_and_failure_status(isolated_server, monkeypatch):
    begin("materials.list")
    aa.handle(payload("RunActionIntent"))
    item = work.list_items()[0]
    monkeypatch.setattr(aa, "_run", lambda *args: "Your saved documents")
    work._execute(None, item["id"])
    assert "Your saved documents" in aa.handle(payload("ActionStatusIntent"))["speech"]
    begin("materials.list")
    aa.handle(payload("RunActionIntent"))
    item = work.list_items()[0]
    def fail(*args):
        raise RuntimeError("private backend details")
    monkeypatch.setattr(aa, "_run", fail)
    work._execute(None, item["id"])
    result = aa.handle(payload("ActionStatusIntent"))
    assert "failed" in result["speech"] and "private backend" not in result["speech"]


def test_model_parameter_answers_dates_lists_and_resolved_field(isolated_server):
    begin("interviews.log")
    answer("Acme")
    answer("Engineer")
    assert "complete date" in answer("next month")["speech"]
    result = aa.handle(payload("DateAnswerIntent", "2026-09-10"))
    assert "interview type" in result["speech"]
    answer("phone_screen")
    change = payload("ChangeFieldIntent", "notes", "Field")
    change["request"]["intent"]["slots"]["Field"]["resolutions"] = {"resolutionsPerAuthority": [{"status": {"code": "ER_SUCCESS_MATCH"}, "values": [{"value": {"id": "tags"}}]}]}
    assert "commas" in aa.handle(change)["speech"]
    answer("technical, remote")
    aa.handle(payload("AMAZON.YesIntent"))
    assert work.list_items()[0]["inputs"]["params"]["tags"] == ["technical", "remote"]


def test_prompt_types_number_validation_and_status_before_execution(isolated_server):
    begin("wellbeing.checkin")
    assert "the number is" in answer("good")["speech"]
    assert "number" in answer("invalid")["speech"]
    aa.handle(payload("NumberAnswerIntent", "7"))
    aa.handle(payload("AMAZON.YesIntent"))
    assert "queued" in aa.handle(payload("ActionStatusIntent"))["speech"]
    assert work.list_items()[0]["inputs"]["params"]["energy"] == 7


def test_missing_identifiers_catalog_and_nonpending_controls(isolated_server):
    data = payload("ActionCatalogIntent")
    data["session"] = {}
    assert "launch" in aa.handle(data)["speech"]
    assert "search jobs" in aa.handle(payload("ActionCatalogIntent"))["speech"]
    assert "no recent" in aa.handle(payload("ActionStatusIntent"))["speech"]
    assert "no pending" in aa.handle(payload("AnswerIntent", "stray answer"))["speech"]


def test_text_rendering_strips_formatting_and_code():
    assert aa.plain("# Title\n[Name](https://example.com) ```private code``` https://example.com <b>word</b>") == "Title Name [Code is available in your workspace.] [link in workspace] word"


def test_execution_does_not_dispatch_duplicate_notifications(isolated_server, monkeypatch):
    seen = []
    work.register_kind("test.once", lambda inputs: seen.append(1) or {})
    item = work.enqueue("test.once", {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: work._execute(None, item), range(2)))
    assert seen == [1]


def test_inline_work_does_not_notify_dispatcher(isolated_server, monkeypatch):
    notified = []
    monkeypatch.setattr(work, "_notify", lambda *args: notified.append(args))
    work.register_kind("test.inline", lambda inputs: {"done": True})
    assert work.run_now("test.inline", {})["status"] == "succeeded"
    assert notified == []


def test_worker_restores_verified_user_oid(monkeypatch):
    from lib.user_context import get_current_user_oid
    monkeypatch.setattr(aa, "_run", lambda *args: get_current_user_oid())
    result = aa.execute({"key": "wellbeing.oura_get", "params": {}, "oid": "alice"})
    assert result["text"] == "alice"
    assert get_current_user_oid() == ""


@pytest.mark.parametrize("next_intent", ["ActionCatalogIntent", "ActionStatusIntent", ACTIONS["workspace.setup"].intent])
def test_switching_requests_discards_prior_confirmation(isolated_server, next_intent):
    begin("materials.reindex")
    aa.handle(payload(next_intent))
    assert "no pending" in aa.handle(payload("AMAZON.YesIntent"))["speech"]
    assert work.list_items() == []


def test_fast_view_clears_pending_confirmation(isolated_server):
    aa.clear_pending(payload("PipelineIntent"))  # no table yet
    begin("materials.reindex")
    aa.clear_pending(payload("PipelineIntent"))
    assert "no pending" in aa.handle(payload("AMAZON.YesIntent"))["speech"]
    assert work.list_items() == []
