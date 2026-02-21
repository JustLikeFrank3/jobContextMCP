"""
Tests for implied daily check-in nudge behavior in job hunt status output.
"""

import server as srv


def test_job_hunt_status_shows_nudge_when_no_checkin_today(isolated_server):
    result = srv.get_job_hunt_status()
    assert "No applications tracked yet" in result
    assert "No check-in logged yet today" in result


def test_job_hunt_status_hides_nudge_after_checkin_today(isolated_server):
    srv.log_mental_health_checkin(mood="stable", energy=5, notes="test")
    result = srv.get_job_hunt_status()
    assert "No applications tracked yet" in result
    assert "No check-in logged yet today" not in result


def test_job_hunt_status_with_apps_still_shows_nudge_when_missing(isolated_server):
    srv.update_application("FanDuel", "Senior Software Engineer", "waiting")
    result = srv.get_job_hunt_status()
    assert "FanDuel" in result
    assert "No check-in logged yet today" in result


def test_job_hunt_status_with_apps_hides_nudge_after_checkin(isolated_server):
    srv.update_application("Ford", "Software Engineer", "applied")
    srv.log_mental_health_checkin(mood="motivated", energy=7)
    result = srv.get_job_hunt_status()
    assert "Ford" in result
    assert "No check-in logged yet today" not in result
