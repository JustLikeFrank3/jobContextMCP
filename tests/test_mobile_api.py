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
    import transport.http.routes.mobile as mobile_mod

    ran = {}
    monkeypatch.setattr(mobile_mod, "_capture_and_assess", lambda url: ran.setdefault("url", url))
    resp = mobile_client.post("/api/capture", json={"url": "https://jobs.example.com/123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "capturing"
    import time
    for _ in range(50):
        if "url" in ran:
            break
        time.sleep(0.05)
    assert ran["url"] == "https://jobs.example.com/123"

    resp = mobile_client.post("/api/capture", json={"url": "javascript:alert(1)"})
    assert resp.status_code == 422
