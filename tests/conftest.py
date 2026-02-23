"""
Shared fixtures for job-search-mcp test suite.

Key design: server.py runs _reconfigure(_load_config()) at import time.
_load_config() falls back to config.example.json when config.json is missing,
so a clean checkout can import server without crashing.  All path globals are
then redirected to a pytest tmp_path via the `isolated_server` fixture, which
calls server._reconfigure(fake_cfg) before each test.

Each test that touches the filesystem should use the `isolated_server` fixture.
Tests that only exercise pure logic (tag resolution, metric maps, etc.) can
import server directly without the fixture.
"""

import json
import shutil
from pathlib import Path

import pytest

import server as srv


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Core fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_server(tmp_path: Path):
    """
    Redirects every server file-path global to a controlled tmp directory.

    Layout under tmp_path:
        data/               ← STATUS_FILE, HEALTH_LOG_FILE, etc.
        resumes/            ← RESUME_FOLDER / master resume stub
        leetcode/           ← LEETCODE_FOLDER / cheatsheet / quick-ref stubs
        spicam/             ← SPICAM_FOLDER stub

    Yields the tmp_path root.  After the test, globals are restored to their
    original production values so other tests are unaffected.
    """
    data_dir  = tmp_path / "data"
    res_dir   = tmp_path / "resumes"
    lc_dir    = tmp_path / "leetcode"
    sc_dir    = tmp_path / "spicam"
    for d in (data_dir, res_dir, lc_dir, sc_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Stub files so _read() calls don't blow up
    _write(res_dir / "master_resume.txt", "[TEST MASTER RESUME]")
    _write(lc_dir  / "cheatsheet.md",     "[TEST CHEATSHEET]")
    _write(lc_dir  / "quick_ref.md",      "[TEST QUICK REFERENCE]")
    # Stub reference files required by _reconfigure
    _write(res_dir / "template_format.txt",    "[TEST TEMPLATE FORMAT]")
    _write(res_dir / "gm_awards.txt",           "[TEST GM AWARDS]")
    _write(res_dir / "feedback_received.txt",   "[TEST FEEDBACK]")
    _write(res_dir / "skills_shorter.txt",      "[TEST SKILLS]")

    # Minimal status so get_job_hunt_status() has something to read
    _write_json(data_dir / "status.json", {"applications": [], "pipeline_summary": "TEST"})

    fake_cfg = {
        "resume_folder":              str(res_dir),
        "leetcode_folder":            str(lc_dir),
        "spicam_folder":              str(sc_dir),
        "data_folder":                str(data_dir),
        "master_resume_path":         "master_resume.txt",
        "leetcode_cheatsheet_path":   "cheatsheet.md",
        "quick_reference_path":       "quick_ref.md",
        "resume_template_png":        "resume_template.png",
        "cover_letter_template_png":  "cover_letter_template.png",
        "template_format_path":       "template_format.txt",
        "gm_awards_path":             "gm_awards.txt",
        "feedback_received_path":     "feedback_received.txt",
        "skills_shorter_path":        "skills_shorter.txt",
    }

    # Capture original globals so we can restore them
    original_cfg = {
        "resume_folder":              str(srv.RESUME_FOLDER),
        "leetcode_folder":            str(srv.LEETCODE_FOLDER),
        "spicam_folder":              str(srv.SPICAM_FOLDER),
        "data_folder":                str(srv.DATA_FOLDER),
        "master_resume_path":         srv.MASTER_RESUME.name,
        "leetcode_cheatsheet_path":   srv.LEETCODE_CHEATSHEET.name,
        "quick_reference_path":       srv.QUICK_REFERENCE.name,
        "resume_template_png":        srv.RESUME_TEMPLATE_PNG.name,
        "cover_letter_template_png":  srv.COVER_LETTER_TEMPLATE_PNG.name,
        "template_format_path":       srv.TEMPLATE_FORMAT.name,
        "gm_awards_path":             srv.GM_AWARDS.name,
        "feedback_received_path":     srv.FEEDBACK_RECEIVED.name,
        "skills_shorter_path":        srv.SKILLS_SHORTER.name,
    }

    srv._reconfigure(fake_cfg)
    yield tmp_path
    srv._reconfigure(original_cfg)
