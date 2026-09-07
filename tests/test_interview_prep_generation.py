import json
from types import SimpleNamespace

import pytest

from lib import config, work
from lib.io import _save_json
from tools import interview_prep as prep
from tools.generate_async import generation_status
from transport.http import alexa_actions as aa
from transport.http.alexa_catalog import ACTIONS
from transport.http.alexa_prep import prep_view
from tests.test_alexa_actions import payload


@pytest.fixture
def jobs(isolated_server, monkeypatch):
    _save_json(config.STATUS_FILE, {"applications": [
        {"company": "Acme", "role": "Java Engineer", "notes": "Uses ACA, not Helm."},
        {"company": "Acme", "role": "Python Engineer"},
        {"company": "Other", "role": "Java Engineer"}]})
    _save_json(config.JOB_QUEUE_FILE, {"jobs": [
        {"company": "Acme", "role": "Java Engineer", "jd": "Java, Spring, Azure"}]})
    data = {"summary": "Practice Java and Azure with your saved examples.",
            "sections": [{"title": title, "body": "Practice this answer using your actual experience [resume]. " * 15} for title in prep.SECTIONS]}
    monkeypatch.setattr(config, "get_llm_client", lambda: (object(), "test-model"))
    monkeypatch.setattr(prep, "create_chat_completion", lambda *a, **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))]))
    return data


def test_select_saved_job_requires_disambiguation(jobs):
    assert len(prep.saved_jobs("acme")) == 2
    assert len(prep.resolve_job("Acme", "Java Engineer")["records"]) == 2
    with pytest.raises(ValueError, match="Several"):
        prep.resolve_job("Acme")
    with pytest.raises(ValueError, match="No saved job"):
        prep.resolve_job("Absent")
    assert prep.saved_jobs("") == []


def test_background_prep_saves_and_reads_exact_role(jobs):
    assert "Several" in prep.prepare_interview("Acme")
    assert work.list_items() == []
    assert "queued" in prep.prepare_interview("Acme", "Java Engineer")
    item = work.list_items()[0]
    work._execute(None, item["id"])
    result = generation_status(item["id"])
    assert "AI-generated practice" in result
    assert "Likely questions" in result
    assert "Java Engineer" in prep.read_prepared_interview("Acme", "Java Engineer")
    assert "No generated prep" in prep.read_prepared_interview("Acme", "Python Engineer")
    assert "Several" in prep.read_prepared_interview("Acme")
    assert len(list(config.get_active_interview_prep_dir().glob("*.md"))) == 1


def test_missing_provider_does_not_save(jobs, monkeypatch):
    monkeypatch.setattr(config, "get_llm_client", lambda: (None, None))
    with pytest.raises(ValueError, match="configured model"):
        prep.generate({"company": "Acme", "role": "Java Engineer"})
    assert not prep._record_path(prep.resolve_job("Acme", "Java Engineer")).exists()


@pytest.mark.parametrize("data", [{}, {"summary": "x", "sections": []},
    {"summary": "x", "sections": [{"title": "wrong", "body": "bad"}] * 5}])
def test_malformed_model_output_rejected(data):
    with pytest.raises(ValueError):
        prep._validate(data)


def test_sources_are_specific_and_mark_excerpts(jobs):
    sources = prep._sources(prep.resolve_job("Acme", "Java Engineer"))
    text = json.dumps(sources)
    assert "Java, Spring, Azure" in text
    assert "Python Engineer" not in text
    assert "Other" not in text
    assert "Source excerpt" in prep._bounded("x" * 21, 20)


def test_alexa_disambiguates_confirms_generates_and_pages(jobs):
    begin = aa.handle(payload(ACTIONS["interviews.prepare"].intent, "Acme", "PrepCompany"))
    assert "2 saved roles" in begin["speech"]
    assert work.list_items() == []
    ready = aa.handle(payload("AnswerIntent", "Java Engineer"))
    assert "yes to confirm" in ready["speech"]
    assert "Java Engineer" in ready["speech"]
    aa.handle(payload("RunActionIntent"))
    assert work.list_items() == []
    confirm = payload("AMAZON.YesIntent")
    aa.handle(confirm)
    aa.handle(confirm)
    assert len(work.list_items()) == 1
    item = work.list_items()[0]
    work._execute(None, item["id"])
    result = aa.handle(payload("ActionStatusIntent"))
    assert "Prep saved for Java Engineer" in result["speech"]
    assert len(result["rows"]) == 5
    assert "Practice this answer" not in json.dumps(result["rows"])
    next_page = aa.handle(payload("MoreResultIntent"))
    assert "Positioning" in next_page["speech"]
    assert "Practice this answer" in next_page["speech"]


def test_alexa_read_and_empty_selection(jobs):
    no_match = aa.handle(payload(ACTIONS["interviews.prepare"].intent, "Missing", "PrepCompany"))
    assert "couldn't match" in no_match["speech"]
    no_prep = aa.execute({"key": "interviews.read_prepared", "params": {"company": "Acme", "role": "Java Engineer"}})
    assert "No saved prep" in no_prep["text"]
    prep.generate({"company": "Acme", "role": "Java Engineer"})
    read = aa.execute({"key": "interviews.read_prepared", "params": {"company": "Acme", "role": "Java Engineer"}})
    assert read["interview_prep"]["company"] == "Acme"


def test_prep_pagination_reaches_end(jobs):
    data = {**jobs, "company": "Acme", "role": "Java Engineer"}
    state = {}
    prep_view(data, state)
    for _ in range(20):
        result = prep_view(data, state, True)
    assert "end of your prep" in result["speech"]


def test_prep_uses_request_workspace_and_preserves_other_role(jobs, isolated_server):
    from lib.user_context import set_data_folder, reset_data_folder
    first = prep.generate({"company": "Acme", "role": "Java Engineer"})
    prep.generate({"company": "Acme", "role": "Python Engineer"})
    assert "Java Engineer" in prep.read_prepared_interview("Acme", "Java Engineer")
    assert len(list(config.get_active_interview_prep_dir().glob("*.md"))) == 2
    token = set_data_folder(isolated_server / "other-tenant")
    try:
        assert prep.saved_jobs("Acme") == []
        assert "No saved job" in prep.read_prepared_interview("Acme", "Java Engineer")
        assert first["company"] == "Acme"
    finally:
        reset_data_folder(token)


def test_missing_master_cannot_generate(jobs, monkeypatch):
    monkeypatch.setattr(prep, "_read", lambda path: "[Error reading master: missing]")
    with pytest.raises(ValueError, match="master resume"):
        prep.generate({"company": "Acme", "role": "Java Engineer"})
