"""
Tests for get_job_hunt_status() and update_application().
"""

import json

import server as srv


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
