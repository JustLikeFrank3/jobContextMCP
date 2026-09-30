"""Voice briefing (insights.briefing): speakable prose for voice assistants.

Contract under test:
- plain prose only — no markdown, box art, or bullet syntax a TTS engine
  would read aloud
- next upcoming interview leads when one exists (spoken day names)
- pipeline shape sentence always present
- single most-urgent action follows the digest's priority order
- pure local reads: must work (and stay fast) with no LLM and no network
"""
from __future__ import annotations

import datetime as _dt

from lib import config
from lib.io import _save_json
from tools import digest


class TestVoiceBriefing:
    def test_empty_workspace_says_pipeline_empty(self, isolated_server):
        out = digest.get_voice_briefing()
        assert "pipeline is empty" in out

    def test_plain_prose_no_markup(self, isolated_server):
        today = _dt.date.today()
        _save_json(config.STATUS_FILE, {"applications": [
            {"company": "Acme", "role": "SWE", "status": "applied",
             "last_updated": today.isoformat()},
        ]})
        out = digest.get_voice_briefing()
        for banned in ("#", "*", "═", "╔", "║", "- ", "\n"):
            assert banned not in out, f"markup {banned!r} leaked into voice output"

    def test_next_interview_leads_with_spoken_day(self, isolated_server):
        today = _dt.date.today()
        _save_json(config.INTERVIEWS_FILE, {"interviews": [
            # Past interview must not win.
            {"id": 1, "company": "Old Corp", "role": "SWE",
             "interview_date": (today - _dt.timedelta(days=2)).isoformat(),
             "interview_type": "technical"},
            {"id": 2, "company": "Acme", "role": "Staff",
             "interview_date": (today + _dt.timedelta(days=1)).isoformat(),
             "interview_type": "hiring_manager"},
        ]})
        out = digest.get_voice_briefing()
        assert out.startswith("Your next interview is tomorrow")
        assert "hiring manager with Acme" in out
        assert "Old Corp" not in out

    def test_pipeline_counts(self, isolated_server):
        today = _dt.date.today().isoformat()
        _save_json(config.STATUS_FILE, {"applications": [
            {"company": "A", "role": "r1", "status": "applied", "last_updated": today},
            {"company": "B", "role": "r2", "status": "researching", "last_updated": today},
            {"company": "C", "role": "r3", "status": "rejected", "last_updated": today},
        ]})
        out = digest.get_voice_briefing()
        assert "2 active applications" in out
        assert "1 waiting on a response" in out

    def test_most_urgent_prefers_drafted_outreach_over_queue(self, isolated_server):
        today = _dt.date.today().isoformat()
        _save_json(config.PEOPLE_FILE, {"people": [
            {"name": "Sam Lee", "company": "Acme", "outreach_status": "drafted"},
        ]})
        _save_json(config.JOB_QUEUE_FILE, {"jobs": [
            {"company": "Beta", "role": "SWE", "status": "pending", "added": today},
        ]})
        out = digest.get_voice_briefing()
        assert "Most urgent" in out
        assert "Sam Lee" in out
        assert "Beta" not in out

    def test_queue_decision_surfaces_when_nothing_more_urgent(self, isolated_server):
        _save_json(config.JOB_QUEUE_FILE, {"jobs": [
            {"company": "Beta", "role": "SWE", "status": "evaluated"},
        ]})
        out = digest.get_voice_briefing()
        assert "Beta" in out and "awaiting a decision" in out

    def test_recent_progress_sentence(self, isolated_server):
        today = _dt.date.today().isoformat()
        _save_json(config.STATUS_FILE, {"applications": [
            {"company": "Acme", "role": "SWE", "status": "applied",
             "last_updated": today,
             "events": [{"type": "recruiter_contact", "date": today}]},
        ]})
        out = digest.get_voice_briefing()
        assert "Recent progress: recruiter contact from Acme." in out

    def test_registered_as_insights_action(self):
        from tools.consolidated import DOMAINS

        target, _summary = DOMAINS["insights"]["briefing"]
        assert target is digest.get_voice_briefing
