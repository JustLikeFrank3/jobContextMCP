"""Mobile companion API: inbox events, push registration, share capture."""
from __future__ import annotations

import pytest


@pytest.fixture()
def mobile_client(monkeypatch, tmp_path):
    import lib.config as cfg
    from lib.user_provisioning import provision_user_data

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cfg, "DATA_FOLDER", str(root), raising=False)
    provision_user_data(root)
    monkeypatch.delenv("API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    reset_settings_cache()
    with TestClient(create_app()) as client:
        yield client
    reset_settings_cache()


def test_inbox_events_from_journal(mobile_client):
    import lib.db as db

    with db.get_connection() as con:
        con.execute(
            "INSERT INTO job_queue (company, role, jd, source, added_date, status) "
            "VALUES ('Acme', 'SWE', 'jd', 'share', date('now'), 'pending')"
        )
        con.execute(
            "UPDATE job_queue SET status='evaluated', fitment_score='8/10' WHERE company='Acme'"
        )
        con.execute(
            "INSERT INTO interviews (timestamp, company, role, interview_date, interview_type) "
            "VALUES ('2026-07-08T15:00:00', 'Acme', 'SWE', date('now'), 'recruiter_screen')"
        )
    resp = mobile_client.get("/api/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    types = [e["type"] for e in events]
    assert "assessment_done" in types
    assert "interview_logged" in types
    done = next(e for e in events if e["type"] == "assessment_done")
    assert done["company"] == "Acme" and "8/10" in done["title"]
    # newest first
    assert events[0]["id"] >= events[-1]["id"]


def test_push_register_validates_token(mobile_client):
    resp = mobile_client.post("/api/push/register", json={"token": "not-a-token"})
    assert resp.status_code == 422
    resp = mobile_client.post(
        "/api/push/register", json={"token": "ExponentPushToken[abc123]", "platform": "ios"}
    )
    assert resp.status_code == 200


def test_capture_kicks_background_assessment(mobile_client, monkeypatch):
    """Capture enqueues a durable work item; the lifespan dispatcher runs it.
    Partition correctness + failure durability live in tests/test_work.py."""
    from lib import work

    ran = {}
    monkeypatch.setitem(
        work._KINDS, "capture_url", lambda inputs: ran.setdefault("url", inputs["url"]) or {}
    )
    resp = mobile_client.post("/api/capture", json={"url": "https://jobs.example.com/123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "capturing"
    assert isinstance(resp.json()["work_id"], int)
    import time
    for _ in range(100):
        if "url" in ran:
            break
        time.sleep(0.05)
    assert ran["url"] == "https://jobs.example.com/123"

    resp = mobile_client.post("/api/capture", json={"url": "javascript:alert(1)"})
    assert resp.status_code == 422


def test_capture_worker_failure_sends_push(monkeypatch):
    """An exception mid-assessment must push a failure AND re-raise so the
    work row records it — the push is a signal, the row is the record."""
    import pytest as _pytest

    import transport.http.routes.mobile as mobile_mod

    pushes = []
    monkeypatch.setattr(
        mobile_mod, "send_push", lambda title, body, data=None: pushes.append((title, data))
    )
    monkeypatch.setattr(
        mobile_mod,
        "_capture_and_assess_inner",
        lambda url, text="": (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with _pytest.raises(RuntimeError):
        mobile_mod._capture_and_assess({"url": "https://jobs.example.com/9"})
    assert pushes and pushes[0][1]["type"] == "capture_failed"


def test_failed_import_fails_work_row_with_one_push(monkeypatch):
    """An unreadable posting must fail the work row with a diagnosable
    one-liner (path + text length + scraper reason) — and send exactly ONE
    push, not 'Import failed' followed by 'Assessment failed'."""
    import pytest as _pytest

    import tools.job_scraper as scraper_mod
    import transport.http.routes.mobile as mobile_mod

    pushes = []
    monkeypatch.setattr(
        mobile_mod, "send_push", lambda title, body, data=None: pushes.append(title)
    )
    monkeypatch.setattr(
        scraper_mod, "scrape_job_url",
        lambda url, auto_queue=True, page_text="": "LinkedIn blocked automated access to https://x",
    )
    with _pytest.raises(mobile_mod.CaptureImportError) as exc:
        mobile_mod._capture_and_assess({"url": "https://www.linkedin.com/jobs/view/1"})
    assert pushes == ["Import failed"]
    msg = str(exc.value)
    assert msg.startswith("import failed for https://www.linkedin.com/jobs/view/1")
    assert "path=server-fetch" in msg and "page_text_len=0" in msg
    assert "LinkedIn blocked" in msg


def test_failed_import_records_client_text_path(monkeypatch):
    import pytest as _pytest

    import tools.job_scraper as scraper_mod
    import transport.http.routes.mobile as mobile_mod

    monkeypatch.setattr(mobile_mod, "send_push", lambda *a, **k: None)
    monkeypatch.setattr(
        scraper_mod, "scrape_job_url",
        lambda url, auto_queue=True, page_text="": "Could not extract a job title from https://x.",
    )
    with _pytest.raises(mobile_mod.CaptureImportError) as exc:
        mobile_mod._capture_and_assess(
            {"url": "https://www.linkedin.com/jobs/view/2", "text": "junk " * 50}
        )
    assert "path=client-text" in str(exc.value)
    assert "page_text_len=250" in str(exc.value)


def test_failed_import_visible_in_work_api(mobile_client, monkeypatch):
    """End to end: authwalled share → failed work row with readable error_head
    in /api/work/stats. The row is the diagnosis; no log archaeology."""
    import time

    import transport.http.routes.mobile as mobile_mod

    monkeypatch.setattr(mobile_mod, "send_push", lambda *a, **k: None)
    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **kw: type("R", (), {"text": "<html>authwall</html>", "status_code": 200,
                                        "raise_for_status": lambda self: None})(),
    )
    resp = mobile_client.post(
        "/api/capture", json={"url": "https://www.linkedin.com/jobs/view/3"}
    )
    work_id = resp.json()["work_id"]
    deadline = time.time() + 5
    item = {}
    while time.time() < deadline:
        item = mobile_client.get(f"/api/work/{work_id}").json()
        if item.get("status") in ("failed", "succeeded"):
            break
        time.sleep(0.05)
    assert item["status"] == "failed"
    assert item["error"].startswith("import failed for https://www.linkedin.com/jobs/view/3")

    stats = mobile_client.get("/api/work/stats").json()
    heads = [f["error_head"] for f in stats["recent_failures"]]
    assert any(h.startswith("import failed for") for h in heads)


def test_successful_import_parses_queue_result(monkeypatch):
    """Regression for the never-worked success path: queue_job returns
    "Scraped <url>\n→ Queued: {company} — {role}. Run evaluate_queued_job…"
    and the worker must extract company/role from THAT (it used to scan for
    "company:"/"role:" lines that never existed, so every good import pushed
    "Import failed" and skipped its assessment — 2026-07-10 field report,
    verified against real work rows)."""
    import tools.job_scraper as scraper_mod
    import transport.http.routes.mobile as mobile_mod

    pushes = []
    monkeypatch.setattr(
        mobile_mod, "send_push", lambda title, body, data=None: pushes.append(title)
    )
    monkeypatch.setattr(
        scraper_mod, "scrape_job_url",
        lambda url, auto_queue=True, page_text="": (
            "Scraped " + url + "\n"
            "→ Queued: Elevance Health — Senior AI Solutions Engineer (Engineer Senior). "
            "Run evaluate_queued_job to assess fitment before deciding."
        ),
    )
    ran = {}

    def fake_assess(company, role, jd):
        ran.update(company=company, role=role)
        return "## Fitment: 8/10"

    monkeypatch.setattr("tools.fitment.run_job_assessment", fake_assess)
    monkeypatch.setattr(
        "lib.db.get_connection",
        lambda: __import__("contextlib").nullcontext(
            type("C", (), {"execute": lambda self, *a: type("R", (), {"fetchone": lambda s: None})()})()
        ),
    )

    out = mobile_mod._capture_and_assess(
        {"url": "https://careers.elevancehealth.com/x/job/ABC?source=LinkedIn", "text": "# jd"}
    )
    assert out["imported"] is True
    assert out["company"] == "Elevance Health"
    assert out["role"] == "Senior AI Solutions Engineer (Engineer Senior)"
    assert ran["company"] == "Elevance Health"  # assessment actually ran
    assert len(pushes) == 1
    assert pushes[0].startswith("Assessment complete") and "8/10" in pushes[0]


def test_already_queued_variant_still_assesses(monkeypatch):
    """Re-sharing a job (dedupe path) must also read as success and re-assess."""
    import tools.job_scraper as scraper_mod
    import transport.http.routes.mobile as mobile_mod

    monkeypatch.setattr(mobile_mod, "send_push", lambda *a, **k: None)
    monkeypatch.setattr(
        scraper_mod, "scrape_job_url",
        lambda url, auto_queue=True, page_text="": (
            "Scraped " + url + "\n"
            "→ Already queued: Cox Automotive — Senior Platform Engineer (status: pending). "
            "Use evaluate_queued_job to assess it."
        ),
    )
    monkeypatch.setattr(
        "tools.fitment.run_job_assessment", lambda c, r, jd: "Score: 9/10 overall"
    )
    monkeypatch.setattr(
        "lib.db.get_connection",
        lambda: __import__("contextlib").nullcontext(
            type("C", (), {"execute": lambda self, *a: type("R", (), {"fetchone": lambda s: None})()})()
        ),
    )
    out = mobile_mod._capture_and_assess({"url": "https://x.example/1"})
    assert out["imported"] is True and out["company"] == "Cox Automotive"
