"""Tests for the web/mobile wellbeing check-in write path
(POST /dashboard/health/checkin) added alongside the interactive form.

The endpoint delegates to tools.health.log_mental_health_checkin — the same
tool the MCP clients use — so a successful POST must produce an entry the
GET payload then reflects, and validation must reject out-of-range input.
"""
from __future__ import annotations


class TestHealthCheckin:
    def test_valid_checkin_persists_and_reflects(self, http_client_noauth):
        resp = http_client_noauth.post(
            "/dashboard/health/checkin",
            json={"mood": "Good", "energy": 8, "notes": "shipped the gate",
                  "productive": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_entries"] >= 1
        assert "confirmation" in body

        latest = body["recent"][0]
        assert latest["energy"] == 8
        assert latest["mood"] == "good"          # normalized to lowercase
        assert latest["notes"] == "shipped the gate"
        assert latest["productive"] is True

    def test_get_payload_sees_posted_entry(self, http_client_noauth):
        http_client_noauth.post(
            "/dashboard/health/checkin",
            json={"mood": "steady", "energy": 5},
        )
        data = http_client_noauth.get("/dashboard/health/data").json()
        assert data["total_entries"] >= 1
        assert data["recent"][0]["energy"] == 5

    def test_energy_out_of_range_rejected(self, http_client_noauth):
        for bad in (0, 11, -3):
            resp = http_client_noauth.post(
                "/dashboard/health/checkin",
                json={"mood": "good", "energy": bad},
            )
            assert resp.status_code == 422, f"energy={bad} should be rejected"

    def test_empty_mood_rejected(self, http_client_noauth):
        resp = http_client_noauth.post(
            "/dashboard/health/checkin",
            json={"mood": "", "energy": 5},
        )
        assert resp.status_code == 422

    def test_notes_optional(self, http_client_noauth):
        resp = http_client_noauth.post(
            "/dashboard/health/checkin",
            json={"mood": "great", "energy": 9},
        )
        assert resp.status_code == 200
        assert resp.json()["recent"][0]["notes"] == ""
