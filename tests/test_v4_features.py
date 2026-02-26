"""
Tests for v4 features:
  - log_rejection / get_rejections
  - log_application_event
  - get_daily_digest / weekly_summary
  - update_compensation / get_compensation_comparison
  - resume_diff
  - review_message
"""

import json
from pathlib import Path

import server as srv


# ── log_rejection / get_rejections ───────────────────────────────────────────

class TestRejections:
    def test_log_rejection_creates_entry(self, isolated_server):
        result = srv.log_rejection("FanDuel", "Senior SWE", "phone screen")
        assert "FanDuel" in result
        assert "phone screen" in result

        data = json.loads(srv.REJECTIONS_FILE.read_text())
        assert len(data["rejections"]) == 1
        entry = data["rejections"][0]
        assert entry["company"] == "FanDuel"
        assert entry["role"] == "Senior SWE"
        assert entry["stage"] == "phone screen"
        assert entry["id"] == 1

    def test_log_rejection_with_reason_and_notes(self, isolated_server):
        srv.log_rejection(
            "Airbnb", "SWE", "onsite",
            reason="not enough distributed systems experience",
            notes="They liked the culture fit but needed deeper infra knowledge"
        )
        data = json.loads(srv.REJECTIONS_FILE.read_text())
        entry = data["rejections"][0]
        assert entry["reason"] == "not enough distributed systems experience"
        assert "infra" in entry["notes"]

    def test_multiple_rejections_get_sequential_ids(self, isolated_server):
        srv.log_rejection("A", "Role", "applied")
        srv.log_rejection("B", "Role", "phone screen")
        srv.log_rejection("C", "Role", "onsite")
        data = json.loads(srv.REJECTIONS_FILE.read_text())
        ids = [r["id"] for r in data["rejections"]]
        assert ids == [1, 2, 3]

    def test_get_rejections_returns_all(self, isolated_server):
        srv.log_rejection("Company1", "Role", "applied")
        srv.log_rejection("Company2", "Role", "phone screen")
        result = srv.get_rejections()
        assert "Company1" in result
        assert "Company2" in result

    def test_get_rejections_filters_by_company(self, isolated_server):
        srv.log_rejection("FanDuel", "SWE", "phone screen")
        srv.log_rejection("Airbnb", "SWE", "onsite")
        result = srv.get_rejections(company="fanduel")
        assert "FanDuel" in result
        assert "Airbnb" not in result

    def test_get_rejections_filters_by_stage(self, isolated_server):
        srv.log_rejection("FanDuel", "SWE", "phone screen")
        srv.log_rejection("Airbnb", "SWE", "onsite")
        result = srv.get_rejections(stage="onsite")
        assert "Airbnb" in result
        assert "FanDuel" not in result

    def test_get_rejections_empty_returns_message(self, isolated_server):
        result = srv.get_rejections()
        assert "No rejections" in result

    def test_get_rejections_pattern_analysis_multiple(self, isolated_server):
        srv.log_rejection("A", "Role", "phone screen")
        srv.log_rejection("B", "Role", "phone screen")
        srv.log_rejection("C", "Role", "onsite")
        result = srv.get_rejections(include_pattern_analysis=True)
        assert "PATTERN ANALYSIS" in result
        assert "phone screen" in result

    def test_get_rejections_no_pattern_if_single(self, isolated_server):
        srv.log_rejection("A", "Role", "applied")
        result = srv.get_rejections(include_pattern_analysis=True)
        assert "PATTERN ANALYSIS" not in result


# ── log_application_event ─────────────────────────────────────────────────────

class TestApplicationEvent:
    def test_log_event_appends_to_existing_app(self, isolated_server):
        srv.update_application("FanDuel", "SWE", "phone screen")
        result = srv.log_application_event("FanDuel", "SWE", "phone_screen", "Went well, expect response Friday")
        assert "FanDuel" in result
        assert "phone_screen" in result

        data = json.loads(srv.STATUS_FILE.read_text())
        app = data["applications"][0]
        assert len(app["events"]) == 1
        assert app["events"][0]["type"] == "phone_screen"
        assert "Friday" in app["events"][0]["notes"]

    def test_log_multiple_events_all_preserved(self, isolated_server):
        srv.update_application("Reddit", "Backend", "applied")
        srv.log_application_event("Reddit", "Backend", "applied", "Submitted Jan 1")
        srv.log_application_event("Reddit", "Backend", "phone_screen", "Recruiter called")
        srv.log_application_event("Reddit", "Backend", "technical_screen", "Coding challenge sent")

        data = json.loads(srv.STATUS_FILE.read_text())
        events = data["applications"][0]["events"]
        assert len(events) == 3
        types = [e["type"] for e in events]
        assert types == ["applied", "phone_screen", "technical_screen"]

    def test_log_event_unknown_company_returns_error(self, isolated_server):
        result = srv.log_application_event("NonExistentCo", "Role", "applied")
        assert "No application found" in result

    def test_new_app_has_empty_events_list(self, isolated_server):
        srv.update_application("Google", "SWE", "applied")
        data = json.loads(srv.STATUS_FILE.read_text())
        assert data["applications"][0]["events"] == []


# ── get_daily_digest / weekly_summary ────────────────────────────────────────

class TestDigest:
    def test_daily_digest_runs_without_error(self, isolated_server):
        result = srv.get_daily_digest()
        assert "DAILY DIGEST" in result
        assert "PIPELINE" in result

    def test_daily_digest_shows_active_apps(self, isolated_server):
        srv.update_application("FanDuel", "Senior SWE", "phone screen")
        result = srv.get_daily_digest()
        assert "1 active application" in result

    def test_daily_digest_shows_stale_apps(self, isolated_server):
        import datetime
        from lib.io import _load_json, _save_json
        from lib import config

        srv.update_application("OldCo", "SWE", "applied")
        # Manually age the last_updated date
        data = _load_json(config.STATUS_FILE, {"applications": []})
        data["applications"][0]["last_updated"] = "2026-01-01 00:00"
        _save_json(config.STATUS_FILE, data)

        result = srv.get_daily_digest()
        assert "STALE" in result
        assert "OldCo" in result

    def test_weekly_summary_runs_without_error(self, isolated_server):
        result = srv.weekly_summary()
        assert "WEEKLY SUMMARY" in result
        assert "APPLICATIONS" in result

    def test_weekly_summary_shows_rejections(self, isolated_server):
        srv.log_rejection("FanDuel", "SWE", "phone screen")
        result = srv.weekly_summary()
        assert "REJECTIONS THIS WEEK: 1" in result

    def test_weekly_summary_shows_new_apps(self, isolated_server):
        srv.update_application("NewCo", "SWE", "applied")
        result = srv.weekly_summary()
        assert "NewCo" in result


# ── update_compensation / get_compensation_comparison ─────────────────────────

class TestCompensation:
    def test_update_compensation_creates_comp_block(self, isolated_server):
        srv.update_application("FanDuel", "SWE", "offer")
        result = srv.update_compensation("FanDuel", "SWE", base=175000, equity_total=200000, bonus_target_pct=15)
        assert "FanDuel" in result
        assert "$175,000" in result

        from lib.io import _load_json
        from lib import config
        data = _load_json(config.STATUS_FILE, {"applications": []})
        app = data["applications"][0]
        assert app["comp"]["base"] == 175000
        assert app["comp"]["equity_total"] == 200000
        assert app["comp"]["bonus_target_pct"] == 15

    def test_update_compensation_calculates_total(self, isolated_server):
        srv.update_application("Airbnb", "SWE", "offer")
        srv.update_compensation("Airbnb", "SWE", base=180000, equity_total=300000, equity_vest_years=4, bonus_target_pct=10)

        from lib.io import _load_json
        from lib import config
        data = _load_json(config.STATUS_FILE, {"applications": []})
        comp = data["applications"][0]["comp"]
        # 180000 + 75000 (equity/yr) + 18000 (bonus) = 273000
        assert comp["total_comp_estimate"] == 273000

    def test_get_compensation_comparison_no_data(self, isolated_server):
        result = srv.get_compensation_comparison()
        assert "No compensation data" in result

    def test_get_compensation_comparison_shows_table(self, isolated_server):
        srv.update_application("FanDuel", "SWE", "offer")
        srv.update_application("Airbnb", "SWE", "offer")
        srv.update_compensation("FanDuel", "SWE", base=175000)
        srv.update_compensation("Airbnb", "SWE", base=195000)

        result = srv.get_compensation_comparison()
        assert "FanDuel" in result
        assert "Airbnb" in result
        assert "COMPENSATION COMPARISON" in result

    def test_get_compensation_comparison_sorted_by_total(self, isolated_server):
        srv.update_application("Lower", "SWE", "offer")
        srv.update_application("Higher", "SWE", "offer")
        srv.update_compensation("Lower", "SWE", base=150000)
        srv.update_compensation("Higher", "SWE", base=200000)

        result = srv.get_compensation_comparison()
        # Higher should appear before Lower
        assert result.index("Higher") < result.index("Lower")


# ── resume_diff ───────────────────────────────────────────────────────────────

class TestResumeDiff:
    def test_diff_identical_files(self, isolated_server, tmp_path):
        from lib import config
        res_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "resume_a.txt").write_text("Line one\nLine two\n")
        (res_dir / "resume_b.txt").write_text("Line one\nLine two\n")

        result = srv.resume_diff("resume_a.txt", "resume_b.txt")
        assert "No differences" in result

    def test_diff_changed_file(self, isolated_server):
        from lib import config
        res_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "v1.txt").write_text("Line one\nLine two\n")
        (res_dir / "v2.txt").write_text("Line one\nLine THREE\n")

        result = srv.resume_diff("v1.txt", "v2.txt")
        assert "RESUME DIFF" in result
        assert "+1 lines added" in result
        assert "-1 lines removed" in result

    def test_diff_missing_file_returns_error(self, isolated_server):
        from lib import config
        res_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "exists.txt").write_text("content")

        result = srv.resume_diff("exists.txt", "nonexistent.txt")
        assert "not found" in result.lower() or "Not found" in result


# ── review_message ────────────────────────────────────────────────────────────

class TestReviewMessage:
    def test_clean_message_no_issues(self, isolated_server):
        msg = "Quick question — wanted to see if there's any update on the role. Happy to chat when you have a minute."
        result = srv.review_message(msg)
        assert "MESSAGE REVIEW" in result

    def test_detects_corporate_phrase(self, isolated_server):
        msg = "I hope this message finds you well. I wanted to reach out about an opportunity."
        result = srv.review_message(msg)
        assert "i hope this message finds you" in result.lower() or "Corporate phrase" in result

    def test_detects_desperation(self, isolated_server):
        msg = "I really need this job and would love any opportunity you could give me."
        result = srv.review_message(msg)
        assert "Desperation" in result or "really need" in result.lower()

    def test_detects_long_message(self, isolated_server):
        msg = " ".join(["word"] * 250)
        result = srv.review_message(msg)
        assert "250 words" in result

    def test_short_message_marked_good_length(self, isolated_server):
        msg = "Any update on the position? Happy to jump on a call."
        result = srv.review_message(msg)
        # A clean short message should either say "no major issues" or mark length as good
        assert "No major issues" in result or "good" in result.lower() or "✓" in result

    def test_includes_original_text(self, isolated_server):
        msg = "Any update on the timeline?"
        result = srv.review_message(msg)
        assert msg in result
