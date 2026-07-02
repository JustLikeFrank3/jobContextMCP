import datetime as dt

from transport.http.routes.login_page import login_html
from tools import digest, health, session, tone


def test_login_html_urlencodes_next_target():
    html = login_html("/dashboard/settings?tab=profile&return=/dashboard")

    assert "__NEXT_HREF__" not in html
    assert "%2Fdashboard%2Fsettings%3Ftab%3Dprofile%26return%3D%2Fdashboard" in html


def test_login_html_defaults_next_to_react_app():
    """Default sign-in lands on the React SPA (/app), not the legacy dashboard."""
    html = login_html()

    assert "__NEXT_HREF__" not in html
    assert "/dashboard/login?next=%2Fapp" in html


def test_get_session_context_combines_all_sections(monkeypatch):
    monkeypatch.setattr(session.config, "get_contact_name", lambda default: "Frank")
    monkeypatch.setattr(session, "_load_master_context", lambda: "MASTER")
    monkeypatch.setattr(session, "get_tone_profile", lambda: "TONE")
    monkeypatch.setattr(session, "get_all_star_context", lambda: "STAR")
    monkeypatch.setattr(session, "get_job_hunt_status", lambda: "STATUS")
    monkeypatch.setattr(session, "get_people", lambda: "PEOPLE")

    result = session.get_session_context()

    assert "SESSION CONTEXT — Frank" in result
    assert "MASTER" in result
    assert "TONE" in result
    assert "STAR" in result
    assert "STATUS" in result
    assert "PEOPLE" in result
    assert "fully contextualized" in result


def test_get_mental_health_log_reports_no_recent_entries(monkeypatch):
    old_date = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    monkeypatch.setattr(
        health,
        "_load_json",
        lambda *args, **kwargs: {"entries": [{"date": old_date, "energy": 5, "mood": "steady"}]},
    )

    result = health.get_mental_health_log(days=7)

    assert result == "No check-ins logged in the past 7 days."


def test_get_mental_health_log_formats_entries_and_low_energy_warning(monkeypatch):
    today = dt.date.today()
    entries = [
        {
            "date": (today - dt.timedelta(days=1)).isoformat(),
            "energy": 2,
            "mood": "tired",
            "productive": False,
            "notes": "rough day",
        },
        {
            "date": today.isoformat(),
            "energy": 4,
            "mood": "steady",
            "productive": True,
            "notes": "",
        },
    ]
    monkeypatch.setattr(health, "_load_json", lambda *args, **kwargs: {"entries": entries})

    result = health.get_mental_health_log(days=14)

    assert "═══ MENTAL HEALTH LOG" in result
    assert "🟥" in result
    assert "🟨" in result
    assert "productive: ✓" in result
    assert "rough day" in result
    assert "Average energy over 14 days: 3.0/10" in result
    assert "extended low-energy period" in result


def test_get_mental_health_log_reports_high_energy_trend(monkeypatch):
    today = dt.date.today()
    entries = [
        {"date": (today - dt.timedelta(days=1)).isoformat(), "energy": 8, "mood": "great", "productive": True},
        {"date": today.isoformat(), "energy": 9, "mood": "locked in", "productive": True},
    ]
    monkeypatch.setattr(health, "_load_json", lambda *args, **kwargs: {"entries": entries})

    result = health.get_mental_health_log(days=7)

    assert "🟩" in result
    assert "Average energy over 7 days: 8.5/10" in result
    assert "strong energy" in result


def test_get_tone_profile_renders_context_and_samples(monkeypatch):
    monkeypatch.setattr(
        tone,
        "_load_json",
        lambda *args, **kwargs: {
            "samples": [
                {"id": 1, "source": "cover_letter", "context": "target register", "text": "First sample", "word_count": 2},
                {"id": 2, "source": "linkedin_post", "context": "", "text": "Second sample", "word_count": 2},
            ]
        },
    )

    result = tone.get_tone_profile()

    assert "═══ TONE PROFILE (2 samples, 4 total words) ═══" in result
    assert "Context: target register" in result
    assert "First sample" in result
    assert "Second sample" in result


def test_budgeted_tone_profiles_handle_empty_samples(monkeypatch):
    monkeypatch.setattr(tone, "_load_json", lambda *args, **kwargs: {"samples": []})

    assert tone.get_tone_profile_budgeted() == tone._NO_TONE_SAMPLES_MESSAGE
    assert tone.get_cover_letter_tone_profile_budgeted() == tone._NO_TONE_SAMPLES_MESSAGE


def test_get_tone_profile_budgeted_selects_diverse_samples_in_order(monkeypatch):
    samples = [
        {"id": 1, "source": "cover_letter", "context": "target register", "text": "alpha", "word_count": 120},
        {"id": 2, "source": "email", "context": "", "text": "beta", "word_count": 100},
        {"id": 3, "source": "email", "context": "", "text": "gamma", "word_count": 100},
    ]
    monkeypatch.setattr(tone, "_load_json", lambda *args, **kwargs: {"samples": samples})
    monkeypatch.setattr("lib.story_retrieval.estimate_tokens", lambda text: 10)

    result = tone.get_tone_profile_budgeted(token_budget=25, max_samples=2)

    assert "Sample #1" in result
    assert "Sample #3" in result
    assert "Sample #2" not in result
    assert result.index("Sample #1") < result.index("Sample #3")


def test_budgeted_tone_profiles_handle_zero_budget_and_oversized_samples(monkeypatch):
    samples = [{"id": 1, "source": "cover_letter", "context": "", "text": "alpha", "word_count": 120}]
    monkeypatch.setattr(tone, "_load_json", lambda *args, **kwargs: {"samples": samples})
    monkeypatch.setattr("lib.story_retrieval.estimate_tokens", lambda text: 5000)

    assert tone.get_tone_profile_budgeted(token_budget=0, max_samples=2) == ""
    assert tone.get_tone_profile_budgeted(token_budget=100, max_samples=2) == ""
    assert tone.get_cover_letter_tone_profile_budgeted(token_budget=0, max_samples=2) == ""
    assert tone.get_cover_letter_tone_profile_budgeted(token_budget=100, max_samples=2) == ""


def test_cover_letter_tone_score_rewards_high_signal_samples():
    strong = {
        "id": 9,
        "source": "cover_letter_workday",
        "context": "Strongest voice sample. Target register. Engineering philosophy.",
        "text": "jobContextMCP helped the model actually sound like me " * 6,
        "word_count": 120,
    }
    weak = {
        "id": 3,
        "source": "short_note",
        "context": "",
        "text": "tiny",
        "word_count": 4,
    }

    assert tone._cover_letter_tone_score(strong) > tone._cover_letter_tone_score(weak)


def test_get_daily_digest_surfaces_actionable_sections(monkeypatch):
    today = dt.date.today()
    recent = today.isoformat()
    stale = (today - dt.timedelta(days=20)).isoformat()
    closed = (today - dt.timedelta(days=5)).isoformat()
    apps = [
        {
            "company": "WaitCo",
            "role": "Platform Engineer",
            "status": "applied",
            "last_updated": recent,
            "events": [{"type": "applied", "date": recent, "notes": "Submitted application. Recruiter replied fast."}],
        },
        {
            "company": "ReviewCo",
            "role": "Backend Engineer",
            "status": "saved",
            "last_updated": stale,
            "events": [],
        },
        {
            "company": "ClosedCo",
            "role": "Staff Engineer",
            "status": "rejected",
            "last_updated": closed,
            "events": [],
        },
    ]
    queue_jobs = [
        {"company": "QueueCo", "role": "Platform Engineer", "status": "pending"},
        {"company": "ScoreCo", "role": "AI Engineer", "status": "evaluated", "fitment_score": "8/10"},
    ]
    people = [{"name": "Alex", "company": "WaitCo", "outreach_status": "drafted"}]

    monkeypatch.setattr(digest, "_load_apps", lambda: apps)
    monkeypatch.setattr(digest, "_load_queue", lambda: queue_jobs)
    monkeypatch.setattr(digest, "_load_rejections", lambda: [{"company": "ClosedCo"}])
    monkeypatch.setattr(digest, "_load_people", lambda: people)
    monkeypatch.setattr(digest, "_load_health", lambda: [])
    monkeypatch.setattr(
        digest,
        "_check_overdue_followups",
        lambda active: ["[FOLLOW-UP] WaitCo — Platform Engineer: send update"],
    )
    monkeypatch.setattr(digest, "get_daily_checkin_nudge", lambda: "NUDGE")

    result = digest.get_daily_digest()

    assert "NEEDS DECISION" in result
    assert "QueueCo" in result
    assert "ACTION  —  FOLLOW-UPS DUE" in result
    assert "ACTION  —  DRAFTED BUT NOT SENT" in result
    assert "WAITING ON OTHERS" in result
    assert "NEEDS REVIEW" in result
    assert "RECENT PROGRESS" in result
    assert "TOTALS: 3 apps tracked  /  1 rejection logged" in result
    assert "Follow up: WaitCo" in result
    assert "NUDGE" in result


def test_get_daily_digest_uses_fallback_focus_without_nudge(monkeypatch):
    today = dt.date.today().isoformat()

    monkeypatch.setattr(digest, "_load_apps", lambda: [])
    monkeypatch.setattr(digest, "_load_queue", lambda: [])
    monkeypatch.setattr(digest, "_load_rejections", lambda: [])
    monkeypatch.setattr(digest, "_load_people", lambda: [])
    monkeypatch.setattr(digest, "_load_health", lambda: [{"date": today, "energy": 7, "mood": "good"}])
    monkeypatch.setattr(digest, "_check_overdue_followups", lambda active: [])
    monkeypatch.setattr(digest, "get_daily_checkin_nudge", lambda: "SHOULD NOT APPEAR")

    result = digest.get_daily_digest()

    assert "Apply to 2-3 new roles" in result
    assert "Log a check-in after the session" in result
    assert "SHOULD NOT APPEAR" not in result


def test_weekly_summary_reports_contacts_and_low_energy(monkeypatch):
    recent = (dt.date.today() - dt.timedelta(days=1)).isoformat()

    monkeypatch.setattr(
        digest,
        "_load_apps",
        lambda: [{"company": "Acme", "role": "Backend Engineer", "status": "applied", "applied_date": recent, "last_updated": recent}],
    )
    monkeypatch.setattr(digest, "_load_rejections", lambda: [{"date": recent, "stage": "phone"}])
    monkeypatch.setattr(
        digest,
        "_load_people",
        lambda: [{"name": "Riley", "company": "Acme", "relationship": "recruiter", "added_at": recent}],
    )
    monkeypatch.setattr(
        digest,
        "_load_health",
        lambda: [{"date": recent, "energy": 3, "mood": "tired", "productive": False}],
    )

    result = digest.weekly_summary()

    assert "CONTACTS ADDED: 1" in result
    assert "Riley (Acme, recruiter)" in result
    assert "Avg energy: 3.0/10" in result
    assert "Productive days: 0/1" in result
    assert "Mood distribution: tired (1x)" in result
    assert "Low-energy week. Be gentle with yourself." in result


def test_weekly_summary_reports_missing_checkins(monkeypatch):
    monkeypatch.setattr(digest, "_load_apps", lambda: [])
    monkeypatch.setattr(digest, "_load_rejections", lambda: [])
    monkeypatch.setattr(digest, "_load_people", lambda: [])
    monkeypatch.setattr(digest, "_load_health", lambda: [])

    result = digest.weekly_summary()

    assert "No check-ins logged this week." in result
