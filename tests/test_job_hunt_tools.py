"""
Tests for get_job_hunt_status() and update_application().
"""

import json
from datetime import date, timedelta
from unittest.mock import patch

import server as srv
from tools.job_hunt import _extract_followup_date, _check_overdue_followups


class TestJobHuntStatus:
    def test_empty_status_returns_prompt(self, isolated_server):
        result = srv.get_job_hunt_status()
        assert "No applications tracked yet" in result

    def test_add_application_then_status_includes_it(self, isolated_server):
        srv.update_application(
            company="FanDuel",
            role="Senior Software Engineer",
            status="phone_screen",
            next_steps="Await recruiter response",
            contact="Cheyenne",
            notes="Referral complete",
        )

        result = srv.get_job_hunt_status()
        assert "FanDuel" in result
        assert "Senior Software Engineer" in result
        assert "phone_screen" in result
        assert "Cheyenne" in result

    def test_update_same_company_and_role_updates_existing(self, isolated_server):
        srv.update_application("Ford", "Software Engineer", "applied", notes="v1")
        srv.update_application("Ford", "Software Engineer", "waiting", notes="v2")

        data = json.loads(srv.STATUS_FILE.read_text())
        apps = data["applications"]
        assert len(apps) == 1
        assert apps[0]["status"] == "waiting"
        assert apps[0]["notes"] == "v2"

    def test_company_fallback_updates_when_role_differs(self, isolated_server):
        srv.update_application("Airbnb", "SE I", "applied")
        srv.update_application("Airbnb", "SE II", "technical_screen")

        data = json.loads(srv.STATUS_FILE.read_text())
        apps = data["applications"]
        assert len(apps) == 1  # company fallback path
        assert apps[0]["role"] == "SE II"
        assert apps[0]["status"] == "technical_screen"

    def test_status_file_last_updated_written(self, isolated_server):
        srv.update_application("Microsoft", "Software Engineer", "applied")
        data = json.loads(srv.STATUS_FILE.read_text())
        assert "last_updated" in data
        assert isinstance(data["last_updated"], str)

    def test_return_value_indicates_added(self, isolated_server):
        result = srv.update_application("Reddit", "Backend Engineer", "applied")
        assert "Added" in result

    def test_return_value_indicates_updated(self, isolated_server):
        srv.update_application("Reddit", "Backend Engineer", "applied")
        result = srv.update_application("Reddit", "Backend Engineer", "waiting")
        assert "Updated" in result

    def test_status_output_includes_last_updated_line(self, isolated_server):
        srv.update_application("GM", "Software Engineer", "waiting")
        result = srv.get_job_hunt_status()
        assert "Last updated:" in result

    def test_optional_fields_omitted_cleanly(self, isolated_server):
        srv.update_application("Delta", "SE", "applied")
        result = srv.get_job_hunt_status()
        assert "Delta" in result
        assert "SE" in result


class TestFollowUpReminders:
    def test_extract_date_standard_format(self):
        d = _extract_followup_date("Send follow-up email on Feb 24.")
        assert d == date(date.today().year, 2, 24)

    def test_extract_date_with_tilde(self):
        d = _extract_followup_date("Follow up by ~Feb 25 if no response.")
        assert d == date(date.today().year, 2, 25)

    def test_extract_date_no_date_returns_none(self):
        assert _extract_followup_date("Await recruiter outreach.") is None

    def test_extract_date_invalid_day_returns_none(self):
        assert _extract_followup_date("Follow up Feb 99") is None

    def test_check_overdue_past_date_flagged(self):
        yesterday = date.today() - timedelta(days=1)
        apps = [{"company": "Google", "role": "SWE", "next_steps": f"Send email by {yesterday.strftime('%b')} {yesterday.day}."}]
        result = _check_overdue_followups(apps)
        assert len(result) == 1
        assert "OVERDUE" in result[0]
        assert "Google" in result[0]

    def test_check_overdue_today_flagged_as_today(self):
        today = date.today()
        apps = [{"company": "Apple", "role": "SWE", "next_steps": f"Nudge on {today.strftime('%b')} {today.day}."}]
        result = _check_overdue_followups(apps)
        assert len(result) == 1
        assert "TODAY" in result[0]

    def test_check_overdue_future_date_not_flagged(self):
        future = date.today() + timedelta(days=5)
        apps = [{"company": "Netflix", "role": "SWE", "next_steps": f"Follow up {future.strftime('%b')} {future.day}."}]
        result = _check_overdue_followups(apps)
        assert result == []

    def test_check_overdue_empty_next_steps_skipped(self):
        apps = [{"company": "Stripe", "role": "SWE", "next_steps": ""}]
        assert _check_overdue_followups(apps) == []

    def test_status_output_shows_overdue_section(self, isolated_server):
        yesterday = date.today() - timedelta(days=1)
        srv.update_application(
            "Mercedes-Benz", "IT Developer", "pending",
            next_steps=f"Send nudge email on {yesterday.strftime('%b')} {yesterday.day}.",
        )
        result = srv.get_job_hunt_status()
        assert "FOLLOW-UP ACTIONS DUE" in result
        assert "Mercedes-Benz" in result

    def test_status_output_no_overdue_section_when_clean(self, isolated_server):
        future = date.today() + timedelta(days=10)
        srv.update_application(
            "Ford", "SE", "applied",
            next_steps=f"Follow up {future.strftime('%b')} {future.day}.",
        )
        result = srv.get_job_hunt_status()
        assert "FOLLOW-UP ACTIONS DUE" not in result
