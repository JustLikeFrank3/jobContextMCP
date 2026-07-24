"""Follow-up queue sanity: staleness timeout, tag exclusions, dismissals.

The queue and Home priorities are derived views — these tests lock in the
liveness rules (a ghosted/ancient thread is not a to-do) and the per-user
dismissal overlay (lib/dismissals) that lets entries be ✕'d out.
"""
from datetime import datetime, timedelta, timezone

from lib import config, dismissals
from transport.http.routes.dashboard import home as home_routes
from transport.http.routes.dashboard import people as people_routes


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


# ===========================================================================
# lib/dismissals — the persistent overlay
# ===========================================================================

class TestDismissals:
    def test_dismiss_and_active_keys(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DISMISSALS_FILE", tmp_path / "dismissals.json")
        dismissals.dismiss("followup", "James Williams")
        dismissals.dismiss("priority", "Apply to 2–3 new roles today", days=14)
        assert dismissals.active_keys("followup") == {"James Williams"}
        assert dismissals.active_keys("priority") == {"Apply to 2–3 new roles today"}

    def test_expired_dismissal_is_inactive(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DISMISSALS_FILE", tmp_path / "dismissals.json")
        dismissals.dismiss("priority", "old one", days=1)
        # Rewrite the stored expiry into the past.
        items = dismissals._load()
        items[0]["until"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        dismissals._save(items)
        assert dismissals.active_keys("priority") == set()

    def test_restore_removes_dismissal(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DISMISSALS_FILE", tmp_path / "dismissals.json")
        dismissals.dismiss("followup", "Kate Griebel")
        dismissals.restore("followup", "Kate Griebel")
        assert dismissals.active_keys("followup") == set()

    def test_redismiss_replaces_prior_entry(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DISMISSALS_FILE", tmp_path / "dismissals.json")
        dismissals.dismiss("followup", "X", days=1)
        dismissals.dismiss("followup", "X")  # now permanent
        items = [i for i in dismissals._load() if i["key"] == "X"]
        assert len(items) == 1
        assert items[0]["until"] is None

    def test_blank_key_ignored(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DISMISSALS_FILE", tmp_path / "dismissals.json")
        dismissals.dismiss("followup", "   ")
        assert dismissals.active_keys("followup") == set()


# ===========================================================================
# People payload — liveness rules
# ===========================================================================

class TestFollowupQueueRules:
    def _payload(self, monkeypatch, people, dismissed=frozenset()):
        monkeypatch.setattr(people_routes, "_load_json", lambda *_a, **_k: people)
        monkeypatch.setattr(
            people_routes.dismissals, "active_keys",
            lambda kind: set(dismissed) if kind == "followup" else set(),
        )
        return people_routes._people_payload()

    def test_ghosted_tag_excluded_from_queue_and_cold(self, monkeypatch):
        payload = self._payload(monkeypatch, [
            {"name": "James Williams", "outreach_status": "sent",
             "last_contacted": _days_ago(1), "tags": ["recruiter", "unresponsive"]},
            {"name": "Isaac", "outreach_status": "sent",
             "last_contacted": _days_ago(1), "tags": ["closed_loop"]},
        ])
        assert payload["follow_up_queue"] == []
        assert payload["gone_cold"] == []

    def test_stale_thread_times_out_to_gone_cold(self, monkeypatch):
        payload = self._payload(monkeypatch, [
            {"name": "Fresh", "outreach_status": "sent", "last_contacted": _days_ago(3)},
            {"name": "Stale", "outreach_status": "sent", "last_contacted": _days_ago(40)},
        ])
        assert [p["name"] for p in payload["follow_up_queue"]] == ["Fresh"]
        assert [p["name"] for p in payload["gone_cold"]] == ["Stale"]
        assert payload["gone_cold_total"] == 1

    def test_no_date_means_timed_out_not_nagging(self, monkeypatch):
        payload = self._payload(monkeypatch, [
            {"name": "Undated", "outreach_status": "follow-up"},
        ])
        assert payload["follow_up_queue"] == []
        assert [p["name"] for p in payload["gone_cold"]] == ["Undated"]

    def test_dismissed_contact_gone_from_both_buckets(self, monkeypatch):
        payload = self._payload(monkeypatch, [
            {"name": "Kayla Moss", "outreach_status": "drafted", "last_contacted": _days_ago(2)},
            {"name": "Robert Afanu", "outreach_status": "drafted", "last_contacted": _days_ago(90)},
        ], dismissed={"Kayla Moss", "Robert Afanu"})
        assert payload["follow_up_queue"] == []
        assert payload["gone_cold"] == []

    def test_timeout_days_configurable(self, monkeypatch):
        monkeypatch.setattr(
            people_routes.config, "get_config_value",
            lambda key, default=None: 60 if key == "followup_timeout_days" else default,
        )
        payload = self._payload(monkeypatch, [
            {"name": "Slow burn", "outreach_status": "sent", "last_contacted": _days_ago(40)},
        ])
        assert [p["name"] for p in payload["follow_up_queue"]] == ["Slow burn"]
        assert payload["followup_timeout_days"] == 60


# ===========================================================================
# HTTP endpoints — dismiss round-trips against the isolated partition
# ===========================================================================

class TestDismissEndpoints:
    def _seed_people(self, people):
        import json
        config.PEOPLE_FILE.write_text(json.dumps(people), encoding="utf-8")

    def test_dismiss_followup_roundtrip(self, http_client_noauth):
        self._seed_people([
            {"name": "James Williams", "outreach_status": "sent", "last_contacted": _days_ago(1)},
        ])
        before = http_client_noauth.get("/dashboard/people/data").json()
        assert [p["name"] for p in before["follow_up_queue"]] == ["James Williams"]

        r = http_client_noauth.post(
            "/dashboard/people/dismiss-followup", json={"name": "James Williams"}
        )
        assert r.status_code == 200 and r.json()["ok"] is True

        after = http_client_noauth.get("/dashboard/people/data").json()
        assert after["follow_up_queue"] == []
        assert after["gone_cold"] == []

    def test_dismiss_followup_restore(self, http_client_noauth):
        self._seed_people([
            {"name": "Kate Griebel", "outreach_status": "sent", "last_contacted": _days_ago(1)},
        ])
        http_client_noauth.post("/dashboard/people/dismiss-followup", json={"name": "Kate Griebel"})
        http_client_noauth.post(
            "/dashboard/people/dismiss-followup", json={"name": "Kate Griebel", "restore": True}
        )
        data = http_client_noauth.get("/dashboard/people/data").json()
        assert [p["name"] for p in data["follow_up_queue"]] == ["Kate Griebel"]

    def test_dismiss_followup_requires_name(self, http_client_noauth):
        r = http_client_noauth.post("/dashboard/people/dismiss-followup", json={"name": "  "})
        assert r.status_code == 400

    def test_dismiss_priority_endpoint_hides_from_home(self, http_client_noauth):
        r = http_client_noauth.post(
            "/api/dashboard/home/dismiss-priority",
            json={"text": "Apply to 2–3 new roles today"},
        )
        assert r.status_code == 200 and r.json()["ok"] is True
        assert dismissals.active_keys("priority") == {"Apply to 2–3 new roles today"}

    def test_dismiss_priority_requires_text(self, http_client_noauth):
        r = http_client_noauth.post("/api/dashboard/home/dismiss-priority", json={"text": ""})
        assert r.status_code == 400


# ===========================================================================
# Home snapshot — priorities respect liveness + dismissals
# ===========================================================================

class TestHomePrioritySanity:
    def _snapshot(self, monkeypatch, people, dismissed_priorities=frozenset()):
        monkeypatch.setattr(home_routes, "_load_apps", lambda: [
            {"company": "Waiting Co", "role": "Eng", "last_updated": _days_ago(1)},
        ])
        monkeypatch.setattr(home_routes, "_load_queue", lambda: [])
        monkeypatch.setattr(home_routes, "_load_people", lambda: people)
        monkeypatch.setattr(home_routes, "_load_health", lambda: [{"date": _days_ago(1)}])
        monkeypatch.setattr(home_routes, "_is_closed", lambda a: False)
        monkeypatch.setattr(home_routes, "_is_waiting", lambda a: True)
        monkeypatch.setattr(home_routes, "_check_overdue_followups", lambda active: [])
        monkeypatch.setattr(
            home_routes.dismissals, "active_keys",
            lambda kind: set(dismissed_priorities) if kind == "priority" else set(),
        )
        return home_routes._build_snapshot()

    def test_ancient_draft_is_not_a_priority(self, monkeypatch):
        snap = self._snapshot(monkeypatch, [
            {"name": "Kayla Moss", "outreach_status": "drafted", "last_contacted": _days_ago(150)},
        ])
        assert snap["drafted_unsent"] == 0
        assert not any("Kayla" in p for p in snap["priorities"])

    def test_ghosted_draft_is_not_a_priority(self, monkeypatch):
        snap = self._snapshot(monkeypatch, [
            {"name": "Robert", "outreach_status": "drafted",
             "last_contacted": _days_ago(2), "tags": ["dormant"]},
        ])
        assert snap["drafted_unsent"] == 0

    def test_fresh_draft_still_is_a_priority(self, monkeypatch):
        snap = self._snapshot(monkeypatch, [
            {"name": "Andy Venditti", "outreach_status": "drafted", "last_contacted": _days_ago(2)},
        ])
        assert "Send message to Andy Venditti" in snap["priorities"]

    def test_dismissed_priority_filtered_out(self, monkeypatch):
        snap = self._snapshot(
            monkeypatch,
            [{"name": "Andy Venditti", "outreach_status": "drafted", "last_contacted": _days_ago(2)}],
            dismissed_priorities={"Send message to Andy Venditti"},
        )
        assert "Send message to Andy Venditti" not in snap["priorities"]
