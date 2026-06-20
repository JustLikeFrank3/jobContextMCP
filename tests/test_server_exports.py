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

import json

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

def _public_functions_defined_in(mod):
    """Yield public callables defined by a tool module, excluding classes."""
    for name, value in vars(mod).items():
        if name.startswith("_") or name == "register":
            continue
        if not callable(value) or isinstance(value, type):
            continue
        if getattr(value, "__module__", "") == mod.__name__:
            yield name, value


def test_all_tool_functions_aliased():
    """Every public callable defined in a tool module is aliased on server."""
    missing = []
    for mod in srv._TOOL_MODULES:
        for name, value in _public_functions_defined_in(mod):
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
    "ACHIEVEMENTS",
    "COVER_LETTER_TEMPLATE_PNG",
    "DATA_FOLDER",
    "FEEDBACK_RECEIVED",
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


# ──────────────────────────────────────────────────────────────────────────────
# 6. Tilde (~) path expansion in _reconfigure
# ──────────────────────────────────────────────────────────────────────────────

def test_reconfigure_expands_tilde_paths(tmp_path):
    """_reconfigure must expand ~ in all user-configured path keys.

    Covers the portability fix: config.json values written as ~/... must resolve
    correctly regardless of where $HOME lives (e.g. an external volume).
    """
    from pathlib import Path
    from lib import config as cfg

    home = Path.home()

    # Build a fake config using ~ notation for every path key.
    # We use the real home dir so expanduser() produces a valid absolute path.
    fake_data   = tmp_path / "data"
    fake_res    = tmp_path / "resumes"
    fake_lc     = tmp_path / "leetcode"
    fake_sp     = tmp_path / "side_project"
    fake_fb     = tmp_path / "fb"
    fake_latex  = tmp_path / "latex"
    for d in (fake_data, fake_res, fake_lc, fake_sp, fake_fb, fake_latex):
        d.mkdir(parents=True, exist_ok=True)

    def _tilde(p: Path) -> str:
        try:
            return "~/" + str(p.relative_to(home))
        except ValueError:
            return str(p)

    tilde_cfg = {
        "resume_folder":          _tilde(fake_res),
        "leetcode_folder":        _tilde(fake_lc),
        "data_folder":            _tilde(fake_data),
        "side_project_folders":   [_tilde(fake_sp)],
        "fb_friends_folder":      _tilde(fake_fb),
        "latex_resume_dir":       _tilde(fake_latex),
        "master_resume_path":     "master.txt",
        "leetcode_cheatsheet_path": "cheat.md",
        "quick_reference_path":   "qref.md",
    }

    # Snapshot originals so we can restore after the test.
    orig_cfg = dict(cfg._cfg) if hasattr(cfg, "_cfg") else {}
    try:
        cfg._reconfigure(tilde_cfg)

        assert cfg.DATA_FOLDER   == fake_data,  f"DATA_FOLDER not expanded: {cfg.DATA_FOLDER}"
        assert cfg.RESUME_FOLDER == fake_res,   f"RESUME_FOLDER not expanded: {cfg.RESUME_FOLDER}"
        assert cfg.LEETCODE_FOLDER == fake_lc,  f"LEETCODE_FOLDER not expanded: {cfg.LEETCODE_FOLDER}"
        assert cfg.SIDE_PROJECT_FOLDERS == [fake_sp], \
            f"SIDE_PROJECT_FOLDERS not expanded: {cfg.SIDE_PROJECT_FOLDERS}"
        assert cfg.FB_FRIENDS_FOLDER == fake_fb, \
            f"FB_FRIENDS_FOLDER not expanded: {cfg.FB_FRIENDS_FOLDER}"
        assert cfg.LATEX_RESUME_DIR == fake_latex, \
            f"LATEX_RESUME_DIR not expanded: {cfg.LATEX_RESUME_DIR}"

        # Verify none of the resolved paths still start with ~
        for attr in ("DATA_FOLDER", "RESUME_FOLDER", "LEETCODE_FOLDER", "LATEX_RESUME_DIR"):
            p = getattr(cfg, attr)
            assert not str(p).startswith("~"), f"{attr} still contains ~: {p}"
    finally:
        if orig_cfg:
            cfg._reconfigure(orig_cfg)


def test_active_config_uses_request_scoped_user_override(isolated_server):
    from lib import config as cfg
    from lib.user_context import reset_data_folder, set_data_folder

    user_dir = cfg.DATA_FOLDER / "users" / "u1"
    workspace = user_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (user_dir / "config.json").write_text(json.dumps({
        "contact": {"name": "Max Batki"},
        "optimized_resumes_dir": "tenant-resumes",
        "cover_letters_dir": "tenant-letters",
        "reference_materials_dir": "tenant-reference",
        "cover_letter_pdfs_dir": "tenant-pdfs",
        "interview_prep_docs_dir": "tenant-prep",
        "job_assessments_dir": "tenant-assessments",
        "openai_model": "gpt-tenant",
    }), encoding="utf-8")

    token = set_data_folder(user_dir)
    try:
        assert cfg.get_contact_name() == "Max Batki"
        assert cfg.get_config_value("openai_model") == "gpt-tenant"
        assert cfg.get_active_optimized_resumes_dir() == workspace / "tenant-resumes"
        assert cfg.get_active_cover_letters_dir() == workspace / "tenant-letters"
        assert cfg.get_active_reference_materials_dir() == workspace / "tenant-reference"
        assert cfg.get_active_cover_letter_pdfs_dir() == workspace / "tenant-pdfs"
        assert cfg.get_active_interview_prep_dir() == workspace / "tenant-prep"
        assert cfg.get_active_job_assessments_dir() == workspace / "tenant-assessments"
    finally:
        reset_data_folder(token)
