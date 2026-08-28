"""Weekly work-search certification — derivation, selection, directory,
immutable snapshots, and the export truth gate."""
import datetime
import json
import re

import pytest

import server as srv
from tests.facade_driver import call_facade
from tools import certification as cert


def _iso(day: datetime.date) -> str:
    return day.isoformat()


# A Saturday in the recent past, so windows are deterministic.
WEEK_END = datetime.date(2026, 7, 25)
IN_WEEK = WEEK_END - datetime.timedelta(days=2)      # Thursday 7/23
BEFORE_WEEK = WEEK_END - datetime.timedelta(days=7)  # previous Saturday
AFTER_WEEK = WEEK_END + datetime.timedelta(days=1)   # Sunday


def _write_status(apps: list[dict]) -> None:
    srv.STATUS_FILE.write_text(
        json.dumps({"applications": apps}), encoding="utf-8"
    )


def _write_interviews(ivs: list[dict]) -> None:
    srv.INTERVIEWS_FILE.write_text(
        json.dumps({"interviews": ivs}), encoding="utf-8"
    )


def _app(company="Acme", role="SWE", status="applied", contact="", events=None,
         applied_date=None) -> dict:
    return {
        "company": company, "role": role, "status": status,
        "contact": contact, "applied_date": applied_date, "events": events or [],
    }


@pytest.fixture()
def workspace(isolated_server):
    _write_status([])
    _write_interviews([])
    yield


# ── derivation ───────────────────────────────────────────────────────────────

class TestDerivation:
    def test_each_activity_kind_derives_from_its_event(self, workspace):
        _write_status([
            _app("AppCo", events=[{"type": "applied", "date": _iso(IN_WEEK), "notes": ""}]),
            _app("ScreenCo", events=[{"type": "phone_screen", "date": _iso(IN_WEEK), "notes": ""}]),
            _app("FollowCo", status="applied", events=[
                {"type": "follow_up_sent", "date": _iso(IN_WEEK), "notes": "checking in"}]),
            _app("ResumeCo", events=[
                {"type": "outreach_sent", "date": _iso(IN_WEEK), "notes": "resume attached for the recruiter"}]),
        ])
        _write_interviews([{
            "timestamp": f"{_iso(IN_WEEK)} 10:00", "company": "InterviewCo",
            "role": "SWE", "interview_date": _iso(IN_WEEK),
            "interview_type": "hiring_manager", "interview_format": "video",
            "interviewer": "Pat",
        }])
        acts = cert.derive_activities(*cert._week_window(WEEK_END), cert.get_state_profile())
        kinds = {a["employer"]: a["kind"] for a in acts}
        assert kinds["AppCo"] == "application_submitted"
        assert kinds["ScreenCo"] == "screening_completed"
        assert kinds["FollowCo"] == "employer_followup"
        assert kinds["ResumeCo"] == "resume_to_recruiter"
        assert kinds["InterviewCo"] == "interview_attended"
        assert all(a["source_event_ids"] for a in acts)

    def test_window_edges_inclusive_and_out_of_window_excluded(self, workspace):
        start, end = cert._week_window(WEEK_END)
        _write_status([
            _app("EdgeStart", events=[{"type": "applied", "date": _iso(start), "notes": ""}]),
            _app("EdgeEnd", events=[{"type": "applied", "date": _iso(end), "notes": ""}]),
            _app("TooEarly", events=[{"type": "applied", "date": _iso(BEFORE_WEEK), "notes": ""}]),
            _app("TooLate", events=[{"type": "applied", "date": _iso(AFTER_WEEK), "notes": ""}]),
        ])
        employers = {a["employer"] for a in cert.derive_activities(start, end, cert.get_state_profile())}
        assert employers == {"EdgeStart", "EdgeEnd"}

    def test_inbound_recruiter_gated_by_profile(self, workspace):
        _write_status([
            _app("InboundCo", events=[
                {"type": "recruiter_contact", "date": _iso(IN_WEEK), "notes": "recruiter reached out"}]),
        ])
        window = cert._week_window(WEEK_END)
        off = cert.derive_activities(*window, cert.get_state_profile())
        assert off == []  # conservative default: inbound does not count
        on = cert.derive_activities(*window, {**cert.get_state_profile(), "counts_inbound_recruiter": True})
        assert [a["kind"] for a in on] == ["inbound_recruiter"]

    def test_week_ends_on_config_shifts_the_window(self, workspace):
        cert.certification_state_profile(mode="set", week_ends_on="Sunday")
        sunday = WEEK_END + datetime.timedelta(days=1)
        end = cert._week_ending_date(cert.get_state_profile(), _iso(sunday))
        assert end == sunday
        # A Saturday week_ending is now rejected.
        assert "✗" in cert._week_ending_date(cert.get_state_profile(), _iso(WEEK_END))

    def test_result_derived_from_subsequent_events(self, workspace):
        _write_status([
            _app("RejectCo", status="rejected", events=[
                {"type": "applied", "date": _iso(IN_WEEK), "notes": ""},
                {"type": "rejected", "date": _iso(AFTER_WEEK), "notes": ""},
            ]),
        ])
        acts = cert.derive_activities(*cert._week_window(WEEK_END), cert.get_state_profile())
        assert acts[0]["result"] == f"Not selected, notified {_iso(AFTER_WEEK)}"

    def test_back_dated_event_files_under_the_week_it_happened(self, workspace):
        """The reason log_application_event takes a date: an activity logged
        days late must land in the week it actually happened, not the week it
        was typed.  Without the back-date it would fall outside this window
        entirely — silently, and on a state filing."""
        srv.update_application("LateLogCo", "SWE", "applied")
        srv.log_application_event(
            "LateLogCo", "SWE", "follow_up_sent", "thank-you note",
            date=_iso(IN_WEEK),
        )
        acts = cert.derive_activities(*cert._week_window(WEEK_END), cert.get_state_profile())
        assert [(a["employer"], a["date"]) for a in acts] == [("LateLogCo", _iso(IN_WEEK))]

    def test_event_logged_today_is_absent_from_the_earlier_week(self, workspace):
        """Control for the test above: same call without a date defaults to
        now, which is outside the (past) reporting window."""
        srv.update_application("LateLogCo", "SWE", "applied")
        srv.log_application_event("LateLogCo", "SWE", "follow_up_sent", "thank-you note")
        acts = cert.derive_activities(*cert._week_window(WEEK_END), cert.get_state_profile())
        assert acts == []


# ── selection ────────────────────────────────────────────────────────────────

class TestSelection:
    def _mk(self, kind, employer, date, strength=None):
        return {
            "kind": kind, "strength": cert._KIND_STRENGTH[kind] if strength is None else strength,
            "employer": employer, "position": "SWE", "date": date, "method": "Email",
            "contact": "", "result": "Awaiting response", "source_event_ids": ["x"],
        }

    def test_prefers_distinct_employers_then_kinds(self):
        acts = [
            self._mk("interview_attended", "Acme", "2026-07-20"),
            self._mk("application_submitted", "Acme", "2026-07-21"),
            self._mk("application_submitted", "Beta", "2026-07-22"),
            self._mk("employer_followup", "Gamma", "2026-07-23"),
        ]
        picked, alternates = cert.select_entries(acts, 3)
        assert [p["employer"] for p in picked] == ["Acme", "Beta", "Gamma"]
        assert len(alternates) == 1 and alternates[0]["employer"] == "Acme"

    def test_never_pads_under_target(self):
        picked, alternates = cert.select_entries(
            [self._mk("application_submitted", "OnlyCo", "2026-07-20")], 3
        )
        assert len(picked) == 1 and alternates == []

    def test_leads_with_strongest_evidence(self):
        acts = [
            self._mk("employer_followup", "Weak", "2026-07-20"),
            self._mk("interview_attended", "Strong", "2026-07-22"),
        ]
        picked, _ = cert.select_entries(acts, 2)
        assert picked[0]["employer"] == "Strong"


# ── employer directory ───────────────────────────────────────────────────────

class TestDirectory:
    def test_agency_routing(self):
        assert cert.employer_of_record("Unknown (SRG Client)") == "SRG"
        assert cert.employer_of_record("Java IoT Developer (via Insight Global)") == "Insight Global"
        assert cert.employer_of_record("Coca-Cola") == "Coca-Cola"

    def test_manual_override_is_never_auto_overwritten(self, workspace, monkeypatch):
        out = cert.override_employer("Acme", {
            "street": "123 Main St", "city": "Atlanta", "state": "GA", "zip": "30303",
        })
        assert "✓" in out and "manual_override" in out
        # Enrichment now has a "better" answer — it must not land.
        monkeypatch.setattr(
            cert, "_web_search_address",
            lambda name: ({"street": "999 Wrong Rd", "city": "Nowhere", "state": "ZZ", "zip": "00000"}, "http://x"),
        )
        monkeypatch.setattr(cert, "_is_stale", lambda row: True)  # force the enrich path
        row = cert.enrich_employer("Acme")
        assert row["street"] == "123 Main St"
        assert row["manual_override"]

    def test_staleness_triggers_reverify_and_fresh_rows_skip_network(self, workspace, monkeypatch):
        calls = []
        monkeypatch.setattr(
            cert, "_web_search_address",
            lambda name: calls.append(name) or (
                {"street": "1 Peachtree St", "city": "Atlanta", "state": "GA", "zip": "30303"}, "http://reg",
            ),
        )
        row = cert.enrich_employer("FreshCo")
        assert row["street"] == "1 Peachtree St" and calls == ["FreshCo"]
        # Second lookup within 90 days: cache hit, no network.
        cert.enrich_employer("FreshCo")
        assert calls == ["FreshCo"]
        # Age the row past the staleness window → re-verify hits the network.
        from lib.db import get_connection

        old = (datetime.date.today() - datetime.timedelta(days=91)).isoformat()
        with get_connection() as con:
            con.execute("UPDATE employer_directory SET verified_at = ?", (old,))
        cert.enrich_employer("FreshCo")
        assert calls == ["FreshCo", "FreshCo"]

    def test_alias_matches_canonical_row(self, workspace):
        cert.override_employer("Cox Automotive", {"street": "6205 Peachtree Rd", "city": "Atlanta", "state": "GA", "zip": "30328"})
        from lib.db import get_connection

        with get_connection() as con:
            row = cert._find_employer(con, "cox automotive")
        assert row is not None and row["street"] == "6205 Peachtree Rd"


# ── reports: freeze, versioning, export gate ─────────────────────────────────

class TestReports:
    def _seed_two_weeks_of_activity(self):
        _write_status([
            _app("Acme", contact="Jane Doe (recruiter)", events=[
                {"type": "applied", "date": _iso(IN_WEEK), "notes": "via portal"}]),
            _app("Beta", events=[
                {"type": "phone_screen", "date": _iso(WEEK_END - datetime.timedelta(days=4)), "notes": ""}]),
            _app("Gamma", status="applied", events=[
                {"type": "follow_up_sent", "date": _iso(WEEK_END - datetime.timedelta(days=1)), "notes": "email nudge"}]),
        ])

    def test_report_freezes_and_lists(self, workspace, monkeypatch):
        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {
            "canonical_name": name, "aliases": [], "street": "1 Test St", "city": "Atlanta",
            "state": "GA", "zip": "30303", "website": "https://x.example",
        })
        self._seed_two_weeks_of_activity()
        out = cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        assert "✓ 3/3" in out and "report #1 v1" in out
        assert "UNDER TARGET" not in out
        listing = cert.list_certification_reports()
        assert "week ending 2026-07-25 v1" in listing
        # Audit trail dual-write landed beside the SQLite row.
        audit = json.loads(srv.CERTIFICATION_AUDIT_FILE.read_text(encoding="utf-8"))
        assert audit["reports"][0]["week_ending"] == _iso(WEEK_END)

    def test_under_target_is_loud_and_never_padded(self, workspace, monkeypatch):
        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {"canonical_name": name, "aliases": []})
        _write_status([
            _app("OnlyCo", events=[{"type": "applied", "date": _iso(IN_WEEK), "notes": ""}]),
        ])
        out = cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        assert "⚠ 1/3" in out and "UNDER TARGET" in out and "NOT padded" in out

    def test_swap_creates_new_version_and_retains_old(self, workspace, monkeypatch):
        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {
            "canonical_name": name, "aliases": [], "street": "1 Test St", "city": "Atlanta",
            "state": "GA", "zip": "30303",
        })
        self._seed_two_weeks_of_activity()
        _write_status(json.loads(srv.STATUS_FILE.read_text(encoding="utf-8"))["applications"] + [
            _app("Delta", events=[{"type": "applied", "date": _iso(IN_WEEK), "notes": ""}]),
        ])
        cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        out = cert.swap_certification_entry(report_id=1, out_entry=1, in_entry="a")
        assert "✓ Swapped" in out and "v2" in out
        listing = cert.list_certification_reports()
        assert "v2" in listing and "v1" in listing  # prior version retained

    def test_export_truth_gate_blocks_untraced_entries(self, workspace):
        from lib.db import get_connection

        profile = cert.get_state_profile()
        entry = {
            "employer": "GhostCo", "address": "1 X St, Atlanta, GA 30303",
            "website": "", "position": "SWE", "date": _iso(IN_WEEK),
            "method": "Email", "contact": "", "result": "Awaiting response",
            "kind": "application_submitted", "source_event_ids": [],
        }
        with get_connection() as con:
            cert._insert_report(con, _iso(WEEK_END), profile, [entry], [], [])
        out = cert.export_certification_report(report_id=1, format="csv")
        assert "EXPORT BLOCKED" in out and "GhostCo" in out

    def test_export_csv_and_portal_text(self, workspace, monkeypatch):
        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {
            "canonical_name": name, "aliases": [], "street": "1 Test St", "city": "Atlanta",
            "state": "GA", "zip": "30303", "website": "https://acme.example",
        })
        self._seed_two_weeks_of_activity()
        cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        csv_out = cert.export_certification_report(report_id=1, format="csv")
        assert "employer,business_address" in csv_out and "Acme" in csv_out
        portal = cert.export_certification_report(report_id=1, format="portal_text")
        assert "Activity 1" in portal and "Business address: 1 Test St, Atlanta, GA 30303" in portal
        # Export history is recorded on the frozen row.
        from lib.db import get_connection

        with get_connection() as con:
            report = cert._load_report(con, 1)
        assert [e["format"] for e in report["exports"]] == ["csv", "portal_text"]


# ── facade dispatch (Layer-1 style integration) ──────────────────────────────

class TestFacade:
    def test_full_weekly_report_through_dispatch(self, workspace, monkeypatch):
        from tools.consolidated import FACADES

        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {"canonical_name": name, "aliases": []})
        _write_status([
            _app("Acme", events=[{"type": "applied", "date": _iso(IN_WEEK), "notes": ""}]),
        ])
        out = call_facade(FACADES["certification"],action="weekly_report", week_ending=_iso(WEEK_END))
        assert "CERTIFICATION WEEK" in out
        assert "needs_address" in cert.list_certification_reports() or "gap" in cert.list_certification_reports()

    def test_state_profile_roundtrip_through_dispatch(self, workspace):
        from tools.consolidated import FACADES

        out = call_facade(FACADES["certification"],action="state_profile", mode="set", min_activities_per_week=5)
        assert "5/week" in out
        assert cert.get_state_profile()["min_activities_per_week"] == 5

    def test_unknown_action_is_a_friendly_error(self):
        from tools.consolidated import FACADES

        out = call_facade(FACADES["certification"],action="weekly_report ")
        assert isinstance(out, str)


# ── dashboard endpoints ──────────────────────────────────────────────────────

class TestDashboard:
    def test_data_endpoint_shape(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(cert, "enrich_employer", lambda name, website_hint="": {"canonical_name": name, "aliases": []})
        resp = http_client_noauth.get("/dashboard/certification/data")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {"configured", "profile", "progress", "reports"}
        assert body["progress"]["target"] == body["profile"]["min_activities_per_week"]

    def test_profile_update_endpoint(self, http_client_noauth):
        resp = http_client_noauth.post(
            "/dashboard/certification/profile", json={"min_activities_per_week": 4}
        )
        assert resp.status_code == 200
        assert cert.get_state_profile()["min_activities_per_week"] == 4

    def test_home_payload_carries_certification_block_when_configured(
        self, http_client_noauth, monkeypatch
    ):
        cert.certification_state_profile(mode="set", min_activities_per_week=3)
        resp = http_client_noauth.get("/api/dashboard/home")
        assert resp.status_code == 200
        block = resp.json()["certification"]
        assert block is not None
        assert set(block) >= {"logged", "target", "label", "onTrack", "weekEnding"}

    def test_home_payload_null_when_unconfigured(self, http_client_noauth):
        resp = http_client_noauth.get("/api/dashboard/home")
        assert resp.status_code == 200
        assert resp.json()["certification"] is None


class TestEnrichmentFixes:
    """Website hints, alias dedupe, spelled street numbers, override coercion."""

    def test_website_hint_skips_job_boards_and_strips_jobs_subdomain(self):
        hint = cert._website_hint_from(
            "posted at https://www.linkedin.com/jobs/view/444 and "
            "https://jobs.mercedes-benz.com/ai-productization-engineer-230835"
        )
        assert hint == "https://mercedes-benz.com"

    def test_website_hint_empty_when_only_ats_urls(self):
        hint = cert._website_hint_from(
            "https://nasdaq.wd1.myworkdayjobs.com/x https://linkedin.com/jobs/1"
        )
        assert hint == ""

    def test_address_regex_accepts_spelled_leading_number(self):
        match = cert._ADDRESS_RE.search(
            "HQ: One Mercedes-Benz Drive, Sandy Springs, GA 30328"
        )
        assert match and match.group("street") == "One Mercedes-Benz Drive"

    def test_address_regex_accepts_plaza(self):
        # Real corporate HQs SerpAPI actually returns: State Farm's is a Plaza.
        match = cert._ADDRESS_RE.search(
            "Headquarters: One State Farm Plaza, Bloomington, IL 61710"
        )
        assert match and match.group("street") == "One State Farm Plaza"
        assert match.group("zip") == "61710"

    def test_alias_activities_merge_into_one(self, workspace):
        _write_interviews([])
        _write_status([
            {"company": "Mercedes", "role": "AI Productization Engineer",
             "status": "applied", "applied_date": _iso(IN_WEEK)},
            {"company": "Mercedes-Benz USA", "role": "AI Productization Engineer",
             "status": "applied", "applied_date": _iso(IN_WEEK)},
        ])
        profile = cert.get_state_profile()
        start, end = cert._week_window(WEEK_END)
        acts = cert.derive_activities(start, end, profile)
        apps = [a for a in acts if a["kind"] == "application_submitted"]
        assert len(apps) == 1
        assert apps[0]["employer"] == "Mercedes-Benz USA"
        assert len(apps[0]["source_event_ids"]) == 2

    def test_override_accepts_json_string(self, workspace):
        out = cert.override_employer(
            "Mercedes-Benz USA",
            '{"street": "One Mercedes-Benz Drive", "city": "Sandy Springs",'
            ' "state": "GA", "zip": "30328"}',
        )
        assert out.startswith("✓")

    def test_override_rejects_malformed_string(self, workspace):
        out = cert.override_employer("Mercedes-Benz USA", "{'nope': True}")
        assert out.startswith("✗ fields must be JSON")


def _freeze_week(monkeypatch) -> int:
    """Freeze WEEK_END with stubbed enrichment; return the new report id."""
    monkeypatch.setattr(
        cert, "enrich_employer",
        lambda name, website_hint="": {"canonical_name": name, "aliases": []},
    )
    out = cert.weekly_certification_report(week_ending=_iso(WEEK_END))
    return int(re.search(r"report #(\d+)", out).group(1))


class TestSubmission:
    """The filed-record stamp: one per week, human-set, survives regeneration."""

    def test_mark_and_list_annotation(self, workspace, monkeypatch):
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        rid = _freeze_week(monkeypatch)
        out = cert.mark_certification_submitted(rid, "GA-778899")
        assert out.startswith("✓") and "SUBMITTED" in out and "GA-778899" in out
        assert "★ SUBMITTED" in cert.list_certification_reports()

    def test_unknown_report_id(self, workspace):
        assert cert.mark_certification_submitted(9999).startswith("✗")

    def test_remark_moves_single_stamp(self, workspace, monkeypatch):
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        rid1 = _freeze_week(monkeypatch)
        rid2 = _freeze_week(monkeypatch)
        assert rid2 != rid1
        cert.mark_certification_submitted(rid1)
        cert.mark_certification_submitted(rid2, "CORRECTED-1")
        from lib.db import get_connection
        with get_connection() as con:
            stamps = cert.submissions_by_week(con)
        assert len(stamps) == 1
        stamp = stamps[_iso(WEEK_END)]
        assert stamp["version"] == 2 and stamp["confirmation_number"] == "CORRECTED-1"

    def test_facade_mark_submitted(self, workspace, monkeypatch):
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        rid = _freeze_week(monkeypatch)
        from tools import consolidated
        out = call_facade(consolidated.certification,
            action="mark_submitted", report_id=rid, confirmation_number="GA-42",
        )
        assert out.startswith("✓") and "GA-42" in out

    def test_archive_week_opens_without_a_stamp(self, http_client_noauth, monkeypatch):
        """Reviewing a week is how you decide what to file, so an unfiled week
        must still resolve to a report — it opens the NEWEST frozen version."""
        _write_interviews([])
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        first = _freeze_week(monkeypatch)
        newest = _freeze_week(monkeypatch)
        assert newest != first
        data = http_client_noauth.get("/dashboard/certification/data").json()
        week = next(w for w in data["archive"] if w["weekEnding"] == _iso(WEEK_END))
        assert week["submittedVersion"] is None
        assert week["reportId"] == newest
        assert week["openVersion"] == 2
        assert week["versions"] == 2

    def test_archive_week_opens_the_filed_version_when_stamped(
        self, http_client_noauth, monkeypatch
    ):
        """Once a week is filed, it opens the FILED version, not the newest —
        the filed record is what matters after the fact."""
        _write_interviews([])
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        filed = _freeze_week(monkeypatch)
        _freeze_week(monkeypatch)  # a later regeneration must not steal the link
        cert.mark_certification_submitted(filed, "GA-9")
        data = http_client_noauth.get("/dashboard/certification/data").json()
        week = next(w for w in data["archive"] if w["weekEnding"] == _iso(WEEK_END))
        assert week["reportId"] == filed and week["openVersion"] == 1

    def test_submit_endpoint_and_archive(self, http_client_noauth, monkeypatch):
        _write_interviews([])
        _write_status([_app("Acme", applied_date=_iso(IN_WEEK))])
        rid = _freeze_week(monkeypatch)
        resp = http_client_noauth.post(
            "/dashboard/certification/submit",
            json={"report_id": rid, "confirmation_number": "GA-1"},
        )
        assert resp.status_code == 200
        data = http_client_noauth.get("/dashboard/certification/data").json()
        week = next(w for w in data["archive"] if w["weekEnding"] == _iso(WEEK_END))
        assert week["submittedVersion"] == 1 and week["confirmation"] == "GA-1"
        assert next(r for r in data["reports"] if r["id"] == rid)["submitted"] is True


class TestDuplicateDetection:
    """One employer, one activity kind, twice in a week — flag, never drop."""

    def _iv(self, date, logged, role="AI Native Engineer", interviewer="Venky"):
        return {
            "timestamp": logged, "company": "Accenture", "role": role,
            "interview_date": date, "interview_type": "hiring_manager",
            "interview_format": "video", "interviewer": interviewer,
        }

    def test_same_event_logged_twice_is_flagged_with_the_tell(self, workspace, monkeypatch):
        # The real shape: two records written an hour apart, different dates.
        _write_interviews([
            self._iv(_iso(IN_WEEK), "2026-07-23 18:57", role="AI Native Engineer / ATC"),
            self._iv(_iso(IN_WEEK - datetime.timedelta(days=1)), "2026-07-23 19:57"),
        ])
        _write_status([])
        monkeypatch.setattr(
            cert, "enrich_employer",
            lambda name, website_hint="": {"canonical_name": name, "aliases": []},
        )
        out = cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        assert "DUPLICATE?" in out and "Accenture" in out
        assert "within 1h of each other" in out
        # Flagged, never silently dropped — both entries still appear.
        assert out.count("Accenture") >= 2

    def test_distinct_rounds_logged_days_apart_get_no_tell(self, workspace, monkeypatch):
        _write_interviews([
            self._iv(_iso(IN_WEEK), "2026-07-21 10:00"),
            self._iv(_iso(IN_WEEK - datetime.timedelta(days=2)), "2026-07-23 10:00"),
        ])
        _write_status([])
        monkeypatch.setattr(
            cert, "enrich_employer",
            lambda name, website_hint="": {"canonical_name": name, "aliases": []},
        )
        out = cert.weekly_certification_report(week_ending=_iso(WEEK_END))
        assert "DUPLICATE?" in out          # still worth a human look
        assert "logged twice" not in out    # but no false accusation

    def test_distinct_employers_are_never_flagged(self, workspace, monkeypatch):
        _write_interviews([
            self._iv(_iso(IN_WEEK), "2026-07-23 18:57"),
            {**self._iv(_iso(IN_WEEK), "2026-07-23 18:58"), "company": "Globex"},
        ])
        _write_status([])
        monkeypatch.setattr(
            cert, "enrich_employer",
            lambda name, website_hint="": {"canonical_name": name, "aliases": []},
        )
        assert "DUPLICATE?" not in cert.weekly_certification_report(week_ending=_iso(WEEK_END))


class TestDdgFallback:
    """Keyless search fallback: company-adjacent addresses only, no network."""

    PAGE = (
        "Ad: Joe's Plumbing Supply — 55 Fake Ave, Nowhere, GA 30000. "
        "Mercedes-Benz USA headquarters: One Mercedes-Benz Drive, "
        "Sandy Springs, GA 30328."
    )

    def test_accepts_address_adjacent_to_company_name(self, monkeypatch):
        monkeypatch.setattr(cert, "_fetch_page", lambda url: self.PAGE)
        found = cert._ddg_search_address("Mercedes-Benz USA")
        assert found and found[0]["street"] == "One Mercedes-Benz Drive"
        assert found[0]["zip"] == "30328"

    def test_rejects_page_with_only_unrelated_addresses(self, monkeypatch):
        monkeypatch.setattr(cert, "_fetch_page", lambda url: self.PAGE)
        assert cert._ddg_search_address("Globex") is None

    def test_fetch_failure_is_silent(self, monkeypatch):
        def boom(url):
            raise RuntimeError("blocked")
        monkeypatch.setattr(cert, "_fetch_page", boom)
        assert cert._ddg_search_address("Mercedes-Benz USA") is None


class TestFacadeDispatch:
    """tools/certification.py uses postponed annotations — the consolidated
    dispatcher must still coerce facade strings to real types."""

    def test_override_fields_json_string_through_facade(self, workspace):
        from tools import consolidated
        out = call_facade(consolidated.certification,
            action="employer_override", name="Acme",
            fields='{"street": "1 Main St", "city": "Atlanta",'
                   ' "state": "GA", "zip": "30303"}',
        )
        assert out.startswith("✓")

    def test_override_fields_dict_through_facade(self, workspace):
        # claude.ai / Claude Code harnesses auto-parse JSON-string args into
        # objects — the facade schema must accept the dict form too.
        from tools import consolidated
        out = call_facade(consolidated.certification,
            action="employer_override", name="DictCo",
            fields={"street": "1 Main St", "city": "Atlanta",
                    "state": "GA", "zip": "30303"},
        )
        assert out.startswith("✓")

    def test_override_fields_double_encoded_string(self, workspace):
        payload = json.dumps(json.dumps({
            "street": "1 Main St", "city": "Atlanta",
            "state": "GA", "zip": "30303",
        }))
        assert cert.override_employer("DoubleCo", payload).startswith("✓")

    def test_activity_kinds_csv_becomes_list_not_characters(self, workspace):
        from tools import consolidated
        out = call_facade(consolidated.certification,
            action="state_profile", mode="set",
            accepted_activity_kinds="application_submitted,interview_attended",
        )
        assert out.startswith("✓")
        kinds = cert.get_state_profile()["accepted_activity_kinds"]
        assert kinds == ["application_submitted", "interview_attended"]
