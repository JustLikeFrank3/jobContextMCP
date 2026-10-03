"""Conference-badge API + badge-scoped API keys.

The load-bearing test in here is scope containment: a badge token is stored in
plain text on hardware that mounts as a USB drive when you double-tap reset, so
"it can only reach /api/badge/*" has to be enforced, not merely intended.
"""
from __future__ import annotations

import time

import pytest

_OID = "badge-user-oid"


@pytest.fixture()
def badge_env(monkeypatch, tmp_path):
    """Entra-provider app (so jcmcp_ keys are honoured) over a temp partition."""
    import lib.config as cfg
    from lib.user_provisioning import provision_user_data

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cfg, "DATA_FOLDER", str(root), raising=False)
    provision_user_data(root)

    # jcmcp_ tokens are only consulted by EntraAuthProvider.
    monkeypatch.setenv("ENTRA_TENANT_ID", "test-tenant")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "test-client")
    monkeypatch.delenv("API_KEY", raising=False)

    from fastapi.testclient import TestClient

    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache
    from transport.http.security import reset_auth_provider_cache

    reset_settings_cache()
    reset_auth_provider_cache()
    with TestClient(create_app()) as client:
        yield client, root
    reset_settings_cache()
    reset_auth_provider_cache()
    # _partition_conn() sets the data-folder contextvar to reach into the
    # tenant partition the way a request would. That contextvar is process
    # global and outlives the test, so without clearing it every later test in
    # the session reads from this (by then deleted) tmp_path.
    from lib.user_context import set_data_folder

    set_data_folder("")


def _key(scope: str) -> str:
    from lib.api_keys import create_key

    _id, plaintext = create_key(oid=_OID, label=f"{scope} key", scope=scope)
    return plaintext


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _partition_conn(root):
    """Open the caller's tenant partition the way a request would see it."""
    import lib.db as db
    from lib.user_context import set_data_folder

    set_data_folder(root / "users" / _OID)
    return db.get_connection()


# ── scope containment ──────────────────────────────────────────────────────────

def test_badge_key_reaches_only_the_badge_surface(badge_env):
    """Containment, proved by contrast: each path below genuinely serves a
    full credential, and refuses a badge one."""
    client, _root = badge_env
    badge_token, full_token = _key("badge"), _key("full")

    assert client.get("/api/badge/ping", headers=_auth(badge_token)).status_code == 200

    for path in ("/api/work", "/api/work/stats", "/api/events"):
        assert client.get(path, headers=_auth(full_token)).status_code == 200, (
            f"{path} does not serve a full key — this test would prove nothing"
        )
        resp = client.get(path, headers=_auth(badge_token))
        assert resp.status_code == 403, f"{path} leaked to a badge key ({resp.status_code})"


def test_badge_key_blocked_before_routing(badge_env):
    """The MCP mount never evaluates route dependencies, so scope has to be
    refused in the middleware. A path the router does not even know about
    still comes back 403 for a badge key — that is the middleware answering."""
    client, _root = badge_env
    assert client.get("/mcp", headers=_auth(_key("full"))).status_code == 404
    assert client.get("/mcp", headers=_auth(_key("badge"))).status_code == 403


def test_full_key_still_reaches_everything(badge_env):
    """The scope gate must not become a regression for ordinary PATs."""
    client, _root = badge_env
    token = _key("full")

    assert client.get("/api/badge/ping", headers=_auth(token)).status_code == 200
    assert client.get("/api/work", headers=_auth(token)).status_code == 200


def test_badge_scope_is_403_never_401(badge_env):
    """A scoped token is authentic — telling the badge to re-authenticate
    would send it round a loop it cannot win."""
    client, _root = badge_env
    resp = client.get("/api/work", headers=_auth(_key("badge")))
    assert resp.status_code == 403
    assert "www-authenticate" not in {h.lower() for h in resp.headers}


def test_bad_token_is_still_401(badge_env):
    client, _root = badge_env
    assert client.get("/api/badge/ping", headers=_auth("jcmcp_nope")).status_code == 401


# ── search ─────────────────────────────────────────────────────────────────────

def test_search_returns_compact_pretruncated_results(badge_env):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))  # provision the partition

    long_role = "Senior Distinguished Principal Staff Engineer, Platform Infrastructure"
    with _partition_conn(root) as con:
        con.execute(
            "INSERT INTO job_queue (company, role, jd, source, added_date, status, fitment_score) "
            "VALUES ('Acme Robotics', ?, 'jd', 'badge', date('now'), 'evaluated', '8/10 — strong')",
            (long_role,),
        )

    body = client.get("/api/badge/search", params={"q": "acme"}, headers=_auth(token)).json()
    assert body["count"] == 1
    hit = body["results"][0]
    assert hit["company"] == "Acme Robotics"
    # Pre-truncated to the badge's line width, ellipsis included.
    assert len(hit["role"]) <= 34 and hit["role"].endswith("…")
    # Only the leading score token survives — the badge has no room for prose.
    assert hit["score"] == "8/10"
    assert isinstance(hit["job_id"], int) and hit["job_id"] > 0


def test_search_matches_role_as_well_as_company(badge_env):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    with _partition_conn(root) as con:
        con.execute(
            "INSERT INTO job_queue (company, role, status) VALUES ('Globex', 'Site Reliability Engineer', 'pending')"
        )
    body = client.get("/api/badge/search", params={"q": "reliability"}, headers=_auth(token)).json()
    assert [r["company"] for r in body["results"]] == ["Globex"]


def test_search_falls_back_to_employer_directory(badge_env):
    """A company you just met at a booth isn't queued yet — an empty screen
    would read as 'search is broken' rather than 'not captured yet'."""
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    with _partition_conn(root) as con:
        con.execute(
            "INSERT INTO employer_directory (canonical_name, city, state, created_at, updated_at) "
            "VALUES ('Initech', 'Austin', 'TX', '', '')"
        )
    body = client.get("/api/badge/search", params={"q": "initech"}, headers=_auth(token)).json()
    hit = body["results"][0]
    assert hit["company"] == "Initech" and hit["status"] == "directory"
    # job_id 0 marks "nothing to generate against yet".
    assert hit["job_id"] == 0


def test_search_requires_a_query(badge_env):
    client, _root = badge_env
    resp = client.get("/api/badge/search", params={"q": "  "}, headers=_auth(_key("badge")))
    assert resp.status_code == 422


# ── material generation ────────────────────────────────────────────────────────

def test_materials_enqueues_and_reports_completion(badge_env, monkeypatch):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    with _partition_conn(root) as con:
        cur = con.execute(
            "INSERT INTO job_queue (company, role, jd, status) VALUES ('Acme', 'SWE', 'jd text', 'pending')"
        )
        job_id = cur.lastrowid

    from lib import work

    monkeypatch.setitem(
        work._KINDS, "badge_materials", lambda inputs: {"resume": "/tmp/acme.pdf"}
    )
    resp = client.post(
        "/api/badge/materials", json={"job_id": job_id, "material": "resume"}, headers=_auth(token)
    )
    assert resp.status_code == 200 and resp.json()["status"] == "queued"
    work_id = resp.json()["work_id"]

    deadline = time.time() + 5
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/badge/work/{work_id}", headers=_auth(token)).json()
        if body.get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "succeeded"
    assert body["made"] == ["resume"]


def test_materials_rejects_unqueued_and_unknown_kinds(badge_env):
    client, _root = badge_env
    token = _key("badge")
    # A directory-only hit carries job_id 0 — there is nothing to generate from.
    assert client.post(
        "/api/badge/materials", json={"job_id": 0, "material": "resume"}, headers=_auth(token)
    ).status_code == 422
    assert client.post(
        "/api/badge/materials", json={"job_id": 1, "material": "manifesto"}, headers=_auth(token)
    ).status_code == 422


def test_poll_never_returns_a_traceback(badge_env, monkeypatch):
    """/api/work hands back full tracebacks; the badge surface must not —
    it's a semi-public credential and a 320x240 screen."""
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    with _partition_conn(root) as con:
        cur = con.execute(
            "INSERT INTO job_queue (company, role, status) VALUES ('Acme', 'SWE', 'pending')"
        )
        job_id = cur.lastrowid

    def boom(inputs):
        raise RuntimeError("secret internal detail " + "x" * 500)

    from lib import work

    monkeypatch.setitem(work._KINDS, "badge_materials", boom)
    work_id = client.post(
        "/api/badge/materials", json={"job_id": job_id, "material": "resume"}, headers=_auth(token)
    ).json()["work_id"]

    deadline = time.time() + 5
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/badge/work/{work_id}", headers=_auth(token)).json()
        if body.get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "failed"
    assert len(body["detail"]) <= 80
    assert "Traceback" not in body["detail"]


def test_poll_404s_on_unknown_work_item(badge_env):
    client, _root = badge_env
    assert client.get("/api/badge/work/999999", headers=_auth(_key("badge"))).status_code == 404


# ── executor ───────────────────────────────────────────────────────────────────

def test_executor_generates_requested_materials(badge_env, monkeypatch):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    with _partition_conn(root) as con:
        cur = con.execute(
            "INSERT INTO job_queue (company, role, jd) VALUES ('Acme', 'SWE', 'the jd')"
        )
        job_id = cur.lastrowid

    calls = []
    monkeypatch.setattr(
        "tools.generate.generate_resume",
        lambda c, r, jd, *a, **k: calls.append(("resume", c, r, jd)) or "✓ Resume generated for SWE @ Acme",
    )
    monkeypatch.setattr(
        "tools.generate.generate_cover_letter",
        lambda c, r, jd, *a, **k: calls.append(("cl", c, r, jd)) or "✓ Cover letter generated for SWE @ Acme",
    )

    import transport.http.routes.badge as badge_mod

    out = badge_mod._generate_materials({"job_id": job_id, "material": "both"})
    assert out["resume"].startswith("✓ Resume") and out["cover_letter"].startswith("✓ Cover letter")
    assert "errors" not in out
    assert [c[0] for c in calls] == ["resume", "cl"]
    # The job's own text reaches the generator, not a placeholder.
    assert calls[0][1:] == ("Acme", "SWE", "the jd")


def test_executor_fails_loudly_on_missing_job(badge_env):
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    import transport.http.routes.badge as badge_mod

    from lib.user_context import set_data_folder

    set_data_folder(root / "users" / _OID)
    with pytest.raises(ValueError, match="not found"):
        badge_mod._generate_materials({"job_id": 424242, "material": "resume"})


def _queue_job(root):
    with _partition_conn(root) as con:
        cur = con.execute(
            "INSERT INTO job_queue (company, role, jd) VALUES ('Acme', 'SWE', 'the jd')"
        )
        return cur.lastrowid


@pytest.mark.live_llm
def test_executor_fails_when_no_llm_is_configured(badge_env, monkeypatch):
    """The real generator, with no LLM client, returns a context package for an
    MCP client to write from — text, not a document. That must fail the row,
    not report made=["resume"] for a file that was never written."""
    # live_llm keeps the real generator; no client sends it down the
    # context-package path, which is what a keyless tenant hits.
    monkeypatch.setattr("tools.generate._openai_client", lambda: None)
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    job_id = _queue_job(root)
    import transport.http.routes.badge as badge_mod
    from lib.user_context import set_data_folder

    set_data_folder(root / "users" / _OID)
    with pytest.raises(RuntimeError, match="no LLM"):
        badge_mod._generate_materials({"job_id": job_id, "material": "resume"})


def test_executor_fails_on_reported_generator_error(badge_env, monkeypatch):
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    job_id = _queue_job(root)
    monkeypatch.setattr(
        "tools.generate.generate_resume",
        lambda *a, **k: "✗ OpenAI API error: 429 rate limited\n\nFalling back to context package:\n…",
    )
    import transport.http.routes.badge as badge_mod
    from lib.user_context import set_data_folder

    set_data_folder(root / "users" / _OID)
    with pytest.raises(RuntimeError, match="429"):
        badge_mod._generate_materials({"job_id": job_id, "material": "resume"})


def test_executor_keeps_the_half_that_worked(badge_env, monkeypatch):
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    job_id = _queue_job(root)
    monkeypatch.setattr(
        "tools.generate.generate_resume",
        lambda *a, **k: "✓ Resume generated for SWE @ Acme\n  ✓ Saved: Acme_SWE_Resume.txt",
    )
    monkeypatch.setattr(
        "tools.generate.generate_cover_letter", lambda *a, **k: "✗ OpenAI API error: boom"
    )
    import transport.http.routes.badge as badge_mod
    from lib.user_context import set_data_folder

    set_data_folder(root / "users" / _OID)
    out = badge_mod._generate_materials({"job_id": job_id, "material": "both"})
    assert out["resume"].startswith("✓ Resume generated")
    assert "cover_letter" not in out
    assert "boom" in out["errors"]["cover_letter"]


def test_poll_detail_is_the_message_not_the_traceback(badge_env, monkeypatch):
    """A short message must not run on into the stored traceback."""
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    job_id = _queue_job(root)

    def no_llm(*a, **k):
        raise RuntimeError("no LLM configured on the server")

    from lib import work

    monkeypatch.setitem(work._KINDS, "badge_materials", no_llm)
    work_id = client.post(
        "/api/badge/materials", json={"job_id": job_id, "material": "resume"}, headers=_auth(token)
    ).json()["work_id"]
    deadline = time.time() + 5
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/badge/work/{work_id}", headers=_auth(token)).json()
        if body.get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert body["detail"] == "no LLM configured on the server"


# ── job search: new openings via SerpAPI ───────────────────────────────────────

_WEB_JOBS = [
    {
        "title": "Senior Software Engineer, Copilot",
        "company_name": "GitHub",
        "location": "Remote, US",
        "description": "Build Copilot. " * 20,
        "apply_options": [{"title": "GitHub", "link": "https://github.careers/1"}],
    },
    {"title": "", "company_name": "Nameless", "description": "dropped: no title"},
    {"title": "Staff Engineer", "company_name": "GitHub", "location": "SF", "via": "LinkedIn"},
]


@pytest.fixture()
def web_search(monkeypatch):
    """Stub the paid SerpAPI call and count how often it is made."""

    import lib.io

    monkeypatch.setattr(lib.io, "_USE_SQLITE", True)
    calls = []

    def fake(query, location=""):
        calls.append(query)
        return _WEB_JOBS

    monkeypatch.setattr("tools.job_scraper._serpapi_jobs", fake)
    return calls


def test_job_search_returns_numbered_openings(badge_env, web_search):
    client, _root = badge_env
    body = client.get("/api/badge/jobs?q=GITHUB", headers=_auth(_key("badge"))).json()
    assert body["count"] == 2  # the untitled result is dropped
    assert [r["number"] for r in body["results"]] == [1, 2]
    assert body["results"][0]["company"] == "GitHub"
    assert body["results"][0]["location"] == "Remote, US"
    assert body["search_id"].startswith("badge-web-")


def test_repeat_job_search_is_served_from_cache(badge_env, web_search):
    client, _root = badge_env
    token = _key("badge")
    first = client.get("/api/badge/jobs?q=GitHub", headers=_auth(token)).json()
    again = client.get("/api/badge/jobs?q=github", headers=_auth(token)).json()
    assert web_search == ["GitHub"]  # one paid call; case-insensitive cache hit
    assert again == first


def test_job_search_daily_cap(badge_env, web_search, monkeypatch):
    import transport.http.routes.badge as badge_mod

    monkeypatch.setattr(badge_mod, "_JOB_SEARCHES_PER_DAY", 2)
    client, _root = badge_env
    token = _key("badge")
    assert client.get("/api/badge/jobs?q=one", headers=_auth(token)).status_code == 200
    assert client.get("/api/badge/jobs?q=two", headers=_auth(token)).status_code == 200
    capped = client.get("/api/badge/jobs?q=three", headers=_auth(token))
    assert capped.status_code == 429 and "limit" in capped.json()["detail"]
    assert web_search == ["one", "two"]
    # A cached query still answers after the cap — it costs nothing.
    assert client.get("/api/badge/jobs?q=one", headers=_auth(token)).status_code == 200


def test_job_search_without_a_key_says_so(badge_env, monkeypatch):
    import lib.config as cfg

    monkeypatch.setattr(cfg, "SERPAPI_KEY", "")
    client, _root = badge_env
    response = client.get("/api/badge/jobs?q=GitHub", headers=_auth(_key("badge")))
    assert response.status_code == 503
    assert "isn't set up" in response.json()["detail"]


def test_job_search_rejects_an_empty_query(badge_env, web_search):
    client, _root = badge_env
    assert client.get("/api/badge/jobs?q=%20", headers=_auth(_key("badge"))).status_code == 422
    assert web_search == []


def test_queue_adds_the_opening_with_its_description(badge_env, web_search):
    client, root = badge_env
    token = _key("badge")
    search_id = client.get("/api/badge/jobs?q=GitHub", headers=_auth(token)).json()["search_id"]

    body = client.post(
        "/api/badge/jobs/queue", json={"search_id": search_id, "number": 1}, headers=_auth(token)
    ).json()
    assert body["status"] == "queued" and body["company"] == "GitHub"

    with _partition_conn(root) as con:
        row = con.execute(
            "SELECT company, role, jd, source FROM job_queue WHERE id = ?", (body["job_id"],)
        ).fetchone()
    assert row["role"] == "Senior Software Engineer, Copilot"
    assert row["jd"].startswith("Build Copilot.")
    assert row["source"] == "https://github.careers/1"

    # The queued opening is now a pipeline hit the materials flow can use.
    hits = client.get("/api/badge/search?q=copilot", headers=_auth(token)).json()["results"]
    assert hits[0]["job_id"] == body["job_id"]


def test_queue_twice_returns_the_same_job(badge_env, web_search):
    client, _root = badge_env
    token = _key("badge")
    search_id = client.get("/api/badge/jobs?q=GitHub", headers=_auth(token)).json()["search_id"]
    payload = {"search_id": search_id, "number": 2}
    first = client.post("/api/badge/jobs/queue", json=payload, headers=_auth(token)).json()
    second = client.post("/api/badge/jobs/queue", json=payload, headers=_auth(token)).json()
    assert second["job_id"] == first["job_id"] and second["status"] == "already queued"


def test_queue_from_an_unknown_search_is_gone(badge_env, web_search):
    client, _root = badge_env
    response = client.post(
        "/api/badge/jobs/queue",
        json={"search_id": "badge-web-nope", "number": 1},
        headers=_auth(_key("badge")),
    )
    assert response.status_code == 410


def test_job_search_is_badge_reachable_but_still_contained(badge_env, web_search):
    """The new paths sit under /api/badge, so a badge key reaches them — and
    nothing about adding them widened what else that key can touch."""
    client, _root = badge_env
    token = _key("badge")
    assert client.get("/api/badge/jobs?q=x", headers=_auth(token)).status_code == 200
    assert client.get("/api/dashboard/api-keys", headers=_auth(token)).status_code == 403


# ── layout / colour choice ─────────────────────────────────────────────────────

def _capture_generators(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        "tools.generate.generate_resume",
        lambda c, r, jd, **k: calls.setdefault("resume", k) and "✓ Resume generated",
    )
    monkeypatch.setattr(
        "tools.generate.generate_cover_letter",
        lambda c, r, jd, **k: calls.setdefault("cover_letter", k) and "✓ Cover letter generated",
    )
    return calls


def test_executor_passes_layout_and_colour_to_both_generators(badge_env, monkeypatch):
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    job_id = _queue_job(root)
    calls = _capture_generators(monkeypatch)
    import transport.http.routes.badge as badge_mod

    badge_mod._generate_materials(
        {"job_id": job_id, "material": "both", "template": "executive", "style": "forest"}
    )
    assert calls["resume"] == {"template": "executive", "style": "forest"}
    assert calls["cover_letter"] == {"cl_template": "executive", "cl_style": "forest"}


def test_executor_defaults_match_old_firmware(badge_env, monkeypatch):
    """A work row from firmware that predates the picker has neither key."""
    client, root = badge_env
    client.get("/api/badge/ping", headers=_auth(_key("badge")))
    job_id = _queue_job(root)
    calls = _capture_generators(monkeypatch)
    import transport.http.routes.badge as badge_mod

    badge_mod._generate_materials({"job_id": job_id, "material": "resume"})
    assert calls["resume"] == {"template": "", "style": "navy"}


def test_materials_rejects_unknown_layout_or_colour(badge_env):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    job_id = _queue_job(root)
    for extra in ({"template": "comic-sans"}, {"template": "modern", "style": "neon"}):
        resp = client.post(
            "/api/badge/materials",
            json={"job_id": job_id, "material": "both", **extra},
            headers=_auth(token),
        )
        assert resp.status_code == 422, extra


def test_materials_records_the_choice_on_the_work_row(badge_env, monkeypatch):
    client, root = badge_env
    token = _key("badge")
    client.get("/api/badge/ping", headers=_auth(token))
    job_id = _queue_job(root)
    from lib import work

    seen = []
    monkeypatch.setitem(work._KINDS, "badge_materials", lambda inputs: seen.append(inputs) or {})
    resp = client.post(
        "/api/badge/materials",
        json={"job_id": job_id, "material": "resume", "template": "sidebar", "style": "warm"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    deadline = time.time() + 5
    while not seen and time.time() < deadline:
        time.sleep(0.05)
    assert seen and seen[0]["template"] == "sidebar" and seen[0]["style"] == "warm"
