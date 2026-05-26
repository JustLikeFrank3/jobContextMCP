"""
Contract tests for server.py auto-export behavior (Phase A1 refactor).

server.py replaced two manual blocks (config-global mirror, function-alias list)
with auto-discovery loops. These tests guard against silent drift:
  - new config paths must appear on `server`
  - new tool functions must appear on `server`
  - re-imported callables must not be re-attributed to the wrong module
  - _reconfigure must re-sync paths after a config swap
  - every historically-exposed name must still resolve (regression boundary)
"""

import server as srv
from lib import config


# ──────────────────────────────────────────────────────────────────────────────
# 1. Config mirror completeness
# ──────────────────────────────────────────────────────────────────────────────

def test_all_config_paths_mirrored():
    """Every public non-callable attribute on lib.config is mirrored onto server."""
    missing = []
    mismatched = []
    for name in dir(config):
        if name.startswith("_"):
            continue
        if not name[0].isupper():
            continue
        value = getattr(config, name)
        if callable(value):
            continue
        if not hasattr(srv, name):
            missing.append(name)
            continue
        if getattr(srv, name) != value:
            mismatched.append(name)
    assert not missing, f"server missing config attrs: {missing}"
    assert not mismatched, f"server config attrs out of sync: {mismatched}"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tool alias completeness
# ──────────────────────────────────────────────────────────────────────────────

def test_all_tool_functions_aliased():
    """Every public callable defined in a tool module is aliased on server."""
    missing = []
    for mod in srv._TOOL_MODULES:
        for name, value in vars(mod).items():
            if name.startswith("_") or name == "register":
                continue
            if not callable(value):
                continue
            # Only require aliases for things DEFINED in this tool module.
            if getattr(value, "__module__", "") != mod.__name__:
                continue
            if getattr(srv, name, None) is not value:
                missing.append(f"{mod.__name__}.{name}")
    assert not missing, f"tool functions not aliased on server: {missing}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. No re-import leakage
# ──────────────────────────────────────────────────────────────────────────────

def test_no_reimport_leakage():
    """update_application is defined in tools.job_hunt but re-imported by
    tools.job_queue. The alias on `server` must point to the original module,
    not the re-import.
    """
    assert srv.update_application.__module__ == "tools.job_hunt"
    assert srv.assess_job_fitment.__module__ == "tools.fitment"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Reconfigure re-syncs paths
# ──────────────────────────────────────────────────────────────────────────────

def test_reconfigure_resyncs_paths(isolated_server, tmp_path):
    """After _reconfigure, server-level config attrs reflect the new paths."""
    # isolated_server fixture has already called _reconfigure(fake_cfg).
    assert srv.STATUS_FILE == tmp_path / "data" / "status.json"
    assert srv.DATA_FOLDER == tmp_path / "data"
    assert srv.RESUME_FOLDER == tmp_path / "resumes"
    # And lib.config matches.
    assert srv.STATUS_FILE == config.STATUS_FILE


# ──────────────────────────────────────────────────────────────────────────────
# 5. Historical exports preserved (regression boundary)
# ──────────────────────────────────────────────────────────────────────────────

# Snapshot of every name previously exposed by the manual alias block in
# server.py before the Phase A1 refactor. If auto-discovery ever fails to pick
# one of these up (renamed function, removed module, missing __module__), this
# test fires loudly before external scripts break.
HISTORICAL_FUNCTION_EXPORTS = {
    "assess_job_fitment",
    "check_workspace",
    "decide_job",
    "draft_outreach_message",
    "evaluate_queued_job",
    "export_cover_letter_pdf",
    "export_resume_pdf",
    "generate_cover_letter",
    "generate_interview_prep_context",
    "generate_resume",
    "get_compensation_comparison",
    "get_customization_strategy",
    "get_daily_digest",
    "get_existing_prep_file",
    "get_hbdi_profile",
    "get_interview_context",
    "get_interview_quick_reference",
    "get_interviews",
    "get_job_hunt_status",
    "get_job_queue",
    "get_leetcode_cheatsheet",
    "get_linkedin_posts",
    "get_mental_health_log",
    "get_people",
    "get_person",
    "get_personal_context",
    "get_rejections",
    "get_star_story_context",
    "get_tone_profile",
    "ingest_anecdote",
    "list_existing_materials",
    "log_application_event",
    "log_interview",
    "log_linkedin_post",
    "log_mental_health_checkin",
    "log_person",
    "log_personal_story",
    "log_rejection",
    "log_tone_sample",
    "queue_job",
    "read_existing_resume",
    "read_master_resume",
    "read_reference_file",
    "reindex_materials",
    "resume_diff",
    "review_message",
    "run_hbdi_assessment",
    "save_interview_prep",
    "scan_materials_for_tone",
    "scan_project_for_skills",
    "search_materials",
    "setup_workspace",
    "update_application",
    "update_compensation",
    "update_post_metrics",
    "weekly_summary",
}


HISTORICAL_CONFIG_EXPORTS = {
    "COVER_LETTER_TEMPLATE_PNG",
    "DATA_FOLDER",
    "FEEDBACK_RECEIVED",
    "GM_AWARDS",
    "INTERVIEW_PREP_FOLDER",
    "JOB_QUEUE_FILE",
    "LEETCODE_CHEATSHEET",
    "LEETCODE_FOLDER",
    "LINKEDIN_POSTS_FILE",
    "MASTER_RESUME",
    "PEOPLE_FILE",
    "PERSONAL_CONTEXT_FILE",
    "QUICK_REFERENCE",
    "REJECTIONS_FILE",
    "RESUME_FOLDER",
    "RESUME_TEMPLATE_PNG",
    "SIDE_PROJECT_FOLDERS",
    "SKILLS_SHORTER",
    "STATUS_FILE",
    "TEMPLATE_FORMAT",
    "TONE_FILE",
}


def test_historical_function_exports_preserved():
    """Every function name in the pre-refactor manual alias block still resolves."""
    missing = HISTORICAL_FUNCTION_EXPORTS - set(dir(srv))
    assert not missing, (
        f"server.py lost historical function exports: {sorted(missing)}\n"
        "These names were previously aliased manually. If renamed/removed "
        "intentionally, update HISTORICAL_FUNCTION_EXPORTS in this test."
    )
    # Each must be callable, not some other attribute.
    not_callable = [n for n in HISTORICAL_FUNCTION_EXPORTS if not callable(getattr(srv, n))]
    assert not not_callable, f"historical exports are not callable: {not_callable}"


def test_historical_config_exports_preserved():
    """Every config-path name in the pre-refactor manual mirror still resolves."""
    missing = HISTORICAL_CONFIG_EXPORTS - set(dir(srv))
    assert not missing, (
        f"server.py lost historical config exports: {sorted(missing)}\n"
        "These paths were previously mirrored manually. If removed from "
        "lib.config intentionally, update HISTORICAL_CONFIG_EXPORTS in this test."
    )
