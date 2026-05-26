"""Tests for Feature-track v0.7 (F1-F5)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib import config
from lib.io import _save_json
from tools import github as gh_tool
from tools import interviews as iv_tool
from tools import people as people_tool
from tools import outreach as outreach_tool


# ──────────────────────────────────────────────────────────────────────────────
# F1: GitHub stats
# ──────────────────────────────────────────────────────────────────────────────

class TestGitHubStats:
    def test_empty_username_returns_warning(self):
        out = gh_tool.get_github_stats("")
        assert out.startswith("⚠")

    def test_offline_mode_returns_stub(self, monkeypatch):
        monkeypatch.setenv("JOBCONTEXTMCP_OFFLINE", "1")
        out = gh_tool.get_github_stats("octocat")
        assert "@octocat" in out
        assert "Offline" in out

    def test_offline_stub_includes_url(self, monkeypatch):
        monkeypatch.setenv("JOBCONTEXTMCP_OFFLINE", "1")
        out = gh_tool.get_github_stats("torvalds")
        assert "https://github.com/torvalds" in out

    def test_network_error_returns_warning(self, monkeypatch):
        monkeypatch.delenv("JOBCONTEXTMCP_OFFLINE", raising=False)

        def boom(*a, **k):
            raise OSError("simulated network failure")

        monkeypatch.setattr(gh_tool, "_http_get_json", boom)
        out = gh_tool.get_github_stats("any")
        assert out.startswith("⚠")
        assert "unable to fetch" in out


# ──────────────────────────────────────────────────────────────────────────────
# F2: get_upcoming_interviews
# ──────────────────────────────────────────────────────────────────────────────

class TestUpcomingInterviews:
    def test_no_interviews(self, isolated_server):
        out = iv_tool.get_upcoming_interviews()
        assert "No interviews" in out

    def test_only_future_within_window(self, isolated_server):
        import datetime as _dt
        today = _dt.date.today()
        _save_json(config.INTERVIEWS_FILE, {"interviews": [
            {"id": 1, "company": "A", "role": "SWE",
             "interview_date": (today - _dt.timedelta(days=3)).isoformat(),
             "interview_type": "technical"},
            {"id": 2, "company": "B", "role": "Staff",
             "interview_date": (today + _dt.timedelta(days=2)).isoformat(),
             "interview_type": "hiring_manager", "interviewer": "Sam"},
            {"id": 3, "company": "C", "role": "Director",
             "interview_date": (today + _dt.timedelta(days=20)).isoformat(),
             "interview_type": "panel"},
        ]})
        out = iv_tool.get_upcoming_interviews(days_ahead=14)
        assert "B" in out and "Sam" in out
        assert "C" not in out  # outside window
        assert "A" not in out  # past

    def test_today_included(self, isolated_server):
        import datetime as _dt
        today = _dt.date.today().isoformat()
        _save_json(config.INTERVIEWS_FILE, {"interviews": [
            {"id": 1, "company": "X", "role": "Y",
             "interview_date": today, "interview_type": "recruiter_screen"},
        ]})
        out = iv_tool.get_upcoming_interviews()
        assert "today" in out


# ──────────────────────────────────────────────────────────────────────────────
# F3: get_referral_chains
# ──────────────────────────────────────────────────────────────────────────────

class TestReferralChains:
    def test_empty_target_warns(self, isolated_server):
        assert people_tool.get_referral_chains("").startswith("⚠")

    def test_no_people(self, isolated_server):
        assert "No contacts" in people_tool.get_referral_chains("Stripe")

    def test_direct_and_adjacent_grouped(self, isolated_server):
        _save_json(config.PEOPLE_FILE, {"people": [
            {"id": 1, "name": "Direct Dee", "relationship": "former coworker",
             "company": "Stripe", "context": "", "tags": [],
             "outreach_status": "none"},
            {"id": 2, "name": "Adjacent Al", "relationship": "friend",
             "company": "OtherCo", "context": "knows folks at Stripe",
             "tags": [], "outreach_status": "none"},
            {"id": 3, "name": "Unrelated Una", "relationship": "recruiter",
             "company": "NoMatch", "context": "", "tags": [],
             "outreach_status": "none"},
        ]})
        out = people_tool.get_referral_chains("Stripe")
        assert "Direct Dee" in out
        assert "Adjacent Al" in out
        assert "Unrelated Una" not in out
        # Headers present and direct precedes adjacent.
        assert out.index("Direct") < out.index("Adjacent")


# ──────────────────────────────────────────────────────────────────────────────
# F4: draft_reply
# ──────────────────────────────────────────────────────────────────────────────

class TestDraftReply:
    def test_empty_incoming_warns(self, isolated_server):
        assert outreach_tool.draft_reply("").startswith("⚠")

    def test_packages_context_sections(self, isolated_server):
        out = outreach_tool.draft_reply(
            "Hey Frank, do you have time Thursday at 2?",
            contact="Sam Recruiter",
            company="Stripe",
            intent="accept",
        )
        assert "INCOMING MESSAGE" in out
        assert "TONE PROFILE" in out
        assert "REPLY INSTRUCTIONS" in out
        assert "INTENT-SPECIFIC POSTURE" in out
        assert "decisive" in out  # accept posture text

    def test_unknown_intent_omits_posture_section(self, isolated_server):
        out = outreach_tool.draft_reply(
            "Hi",
            intent="something_weird",
        )
        assert "INTENT-SPECIFIC POSTURE" not in out


# ──────────────────────────────────────────────────────────────────────────────
# F5: CLI --schedule
# ──────────────────────────────────────────────────────────────────────────────

class TestCliSchedule:
    def _run(self, *args):
        repo = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(repo / "cli.py"), *args],
            capture_output=True, text=True, cwd=str(repo),
        )
        return result

    def test_schedule_requires_tool(self):
        r = self._run("--schedule")
        assert r.returncode != 0
        assert "requires a tool name" in r.stdout + r.stderr

    def test_schedule_unknown_tool(self):
        r = self._run("--schedule", "not_a_real_tool")
        assert r.returncode != 0
        assert "no tool named" in r.stdout + r.stderr

    def test_schedule_emits_crontab_and_plist(self):
        r = self._run("--schedule", "get_daily_digest", "--time", "07:30")
        assert r.returncode == 0
        out = r.stdout
        assert "crontab entry" in out
        assert "30 7 * * *" in out  # minute hour
        assert "<plist" in out
        assert "StartCalendarInterval" in out
        assert "<integer>7</integer>" in out
        assert "<integer>30</integer>" in out

    def test_schedule_default_time(self):
        r = self._run("--schedule", "get_daily_digest")
        assert r.returncode == 0
        # Default 08:00
        assert "0 8 * * *" in r.stdout
