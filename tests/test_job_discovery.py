import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from lib import config, io
from lib.io import _load_json, _save_json
from lib.user_context import set_data_folder, reset_data_folder
from tools import job_discovery as jd

DESCRIPTION = "Build Python services and reliable infrastructure with a collaborative engineering team. " * 10


def job(role="Software Engineer", company="Acme", source="https://jobs.example.com/1", location="Remote US"):
    return dict(company=company, role=role, source=source, location=location, jd=DESCRIPTION, provider="ashby")


@pytest.fixture
def search(isolated_server, monkeypatch):
    jd.save_board("ashby", "acme")
    async def fetch(boards):
        return [([job(), job("Data Engineer", source="https://jobs.example.com/2")], None)]
    monkeypatch.setattr(jd, "_fetch_all", fetch)
    return lambda **kwargs: json.loads(jd.discover_jobs("engineer", **kwargs))


def test_saved_and_inferred_boards(isolated_server):
    _save_json(config.JOB_QUEUE_FILE, {"jobs": [{"company": "Acme", "source": "https://job-boards.greenhouse.io/acme/jobs/1"}]})
    assert "Acme: greenhouse" in jd.list_boards()
    jd.remove_board("greenhouse", "acme")
    assert "No saved" in jd.list_boards()
    jd.save_board("greenhouse", "acme", "Acme Incorporated")
    assert "Acme Incorporated" in jd.list_boards()
    assert "No saved" not in jd.list_boards()


@pytest.mark.parametrize("provider,slug", [("other", "acme"), ("ashby", "../private"), ("recruitee", "evil.com"), ("lever", "x?token=foo"), ("ashby", "")])
def test_board_validation_rejects_arbitrary_targets(isolated_server, provider, slug):
    with pytest.raises(ValueError):
        jd.save_board(provider, slug)


def test_board_limit_and_company_name(isolated_server):
    for n in range(8):
        jd.save_board("lever", f"acme{n}")
    with pytest.raises(ValueError, match="Eight"):
        jd.save_board("ashby", "another")
    jd.save_board("lever", "acme0", "Renamed")
    with pytest.raises(ValueError, match="120"):
        jd.save_board("lever", "acme0", "x" * 121)


def test_search_never_queues_and_selection_preserves_description(search):
    data = search()
    assert len(data["results"]) == 2
    assert "jd" not in data["results"][0]
    assert not _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"]
    selected = json.loads(jd.read_result(data["search_id"], 2))
    assert selected["jd"] == DESCRIPTION
    assert "Queued:" in jd.queue_result(data["search_id"], 2)
    assert "Already queued:" in jd.queue_result(data["search_id"], 2)
    rows = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"]
    assert len(rows) == 1 and rows[0]["jd"] == DESCRIPTION and rows[0]["source"] == selected["source"]


def test_filters_known_jobs_by_pair_and_url(search):
    _save_json(config.JOB_QUEUE_FILE, {"jobs": [{"company": "different", "role": "other", "source": "https://jobs.example.com/1?campaign=x"}]})
    _save_json(config.STATUS_FILE, {"applications": [{"company": "ACME", "role": "DATA ENGINEER"}]})
    assert search()["results"] == []
    assert len(search(include_known=True)["results"]) == 2
    assert search(location="London")["results"] == []
    assert len(search(location="remote", num_results=1, include_known=True)["results"]) == 1


def test_expiry_and_cross_tenant_selection(search, monkeypatch, tmp_path):
    data = search()
    token = set_data_folder(tmp_path / "other-user")
    try:
        assert "No saved" in jd.list_boards()
        with pytest.raises(ValueError, match="unavailable"):
            jd.queue_result(data["search_id"], 1)
    finally:
        reset_data_folder(token)
    now = jd.time.time()
    monkeypatch.setattr(jd.time, "time", lambda: now + jd.TTL + 1)
    with pytest.raises(ValueError, match="expired"):
        jd.queue_result(data["search_id"], 1)


@pytest.mark.parametrize("number", [0, -1, 3, True, 1.5, "1"])
def test_invalid_selection(search, number):
    with pytest.raises(ValueError, match="Choose"):
        jd.queue_result(search()["search_id"], number)


def test_no_boards_and_invalid_query(isolated_server):
    assert "No saved" in json.loads(jd.discover_jobs("engineer"))["message"]
    for query in ("", "jobs", "x" * 241):
        with pytest.raises(ValueError):
            jd.discover_jobs(query)
    with pytest.raises(ValueError):
        jd.discover_jobs("engineer", num_results=21)


@pytest.mark.parametrize("provider,payload", [
    ("greenhouse", {"jobs": [{"title": "Engineer", "location": {"name": "Remote"}, "absolute_url": "https://example.com/job", "content": "<p>" + DESCRIPTION + "</p>"}]}),
    ("lever", [{"text": "Engineer", "categories": {"location": "US"}, "workplaceType": "remote", "hostedUrl": "https://example.com/job", "description": DESCRIPTION, "lists": [{"text": "Requirements", "content": "Python"}]}]),
    ("ashby", {"jobs": [{"title": "Engineer", "location": "US", "isRemote": True, "isListed": True, "jobUrl": "https://example.com/job", "descriptionPlain": DESCRIPTION}]}),
    ("recruitee", {"offers": [{"title": "Engineer", "location": "Remote", "careers_url": "https://example.com/job", "description": DESCRIPTION}]}),
])
def test_provider_parsing(provider, payload):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            return await jd._fetch(client, {"provider": provider, "company_slug": "acme", "company": "Acme"})
    jobs, error = asyncio.run(run())
    assert error is None and len(jobs) == 1 and "Remote" in jobs[0]["location"]
    assert "Python" in jobs[0]["jd"]


@pytest.mark.parametrize("status,body", [(404, "missing"), (200, "not json"), (200, '{"jobs":{}}'), (200, "x" * 8_000_001)], ids=["missing", "malformed", "wrong-shape", "oversized"])
def test_bad_board_is_reported_without_raw_response(status, body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=body))) as client:
            return await jd._fetch(client, {"provider": "ashby", "company_slug": "acme", "company": "Acme"})
    jobs, error = asyncio.run(run())
    assert jobs == [] and "could not be read" in error


def test_partial_failure_and_dedup(search, monkeypatch):
    async def fetch(boards):
        return [([job(), job()], None), ([], "Second board timed out.")]
    monkeypatch.setattr(jd, "_fetch_all", fetch)
    data = search()
    assert len(data["results"]) == 1 and data["errors"] == ["Second board timed out."]


def test_missing_jd_unlisted_and_invalid_link_are_not_queueable():
    board = {"provider": "ashby", "company": "Acme"}
    base = {"title": "Engineer", "jobUrl": "https://example.com/1", "descriptionPlain": DESCRIPTION}
    for change in ({"descriptionPlain": ""}, {"isListed": False}, {"jobUrl": "javascript:alert(1)"}, {"jobUrl": "https://user:password@example.com"}):
        assert jd._normalize(board, base | change) is None


def test_bounded_fetch_timeout(monkeypatch):
    async def timeout(*args):
        raise TimeoutError()
    monkeypatch.setattr(jd, "_fetch", timeout)
    assert "timed out" in asyncio.run(jd._bounded_fetch(None, {"company": "Acme"}))[1]


def test_parallel_board_fetch(monkeypatch):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(jd.httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"jobs": []}))))
    boards = [{"provider": "ashby", "company_slug": f"acme{n}", "company": "Acme"} for n in range(2)]
    assert asyncio.run(jd._fetch_all(boards)) == [([], None), ([], None)]


@pytest.mark.parametrize("source,expected", [("https://jobs.lever.co/acme/123", ("lever", "acme")), ("https://jobs.ashbyhq.com/acme/123", ("ashby", "acme")), ("https://acme.recruitee.com/o/role", ("recruitee", "acme")), ("https://evil.jobs.ashbyhq.com/acme", None)])
def test_source_inference_exact_hosts(source, expected):
    assert jd._source_board(source) == expected


def test_text_decodes_markup():
    assert jd._text("&lt;p&gt;Python &amp; SQL&lt;/p&gt;") == "Python & SQL"


def test_sqlite_queue_concurrent_selections_preserve_existing_rows(search, monkeypatch):
    from lib.db import get_connection
    from lib.user_provisioning import provision_user_data
    from tools.job_queue import queue_job
    # Use the canonical tenant schema and SQLite path, as deployed in QA.
    provision_user_data(config.DATA_FOLDER)
    monkeypatch.setattr(io, "_USE_SQLITE", True)
    data = search()
    queue_job("Existing", "Role", DESCRIPTION)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda n: jd.queue_result(data["search_id"], n), [1, 1, 2]))
    with get_connection() as con:
        rows = con.execute("SELECT company, role, jd FROM job_queue").fetchall()
    assert len(rows) == 3
    assert any(r["company"] == "Existing" for r in rows)
    assert all(r["jd"] == DESCRIPTION for r in rows)
