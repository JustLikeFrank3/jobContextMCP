"""Tests for tools/setup.py — check_workspace and setup_workspace."""
import json
import pytest
from pathlib import Path
from tests.conftest import isolated_server  # noqa: F401


# ── Helpers ────────────────────────────────────────────────────────────────────

_MINIMAL = dict(
    name="Test User",
    email="test@example.com",
    phone="555-000-0000",
    linkedin="linkedin.com/in/testuser",
    city_state="Atlanta, GA",
    master_resume_content="PROFESSIONAL EXPERIENCE\nSoftware Engineer | Acme Co | Jan 2022 - Dec 2025\n• Built things.\n",
)


def _patch_here(monkeypatch, tmp_path: Path, module):
    """Redirect _HERE and derived path constants in tools.setup to tmp_path."""
    monkeypatch.setattr(module, "_HERE", tmp_path)
    monkeypatch.setattr(module, "_WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(module, "_RESUMES_ROOT",   tmp_path / "workspace" / "resumes")
    monkeypatch.setattr(module, "_LEETCODE_ROOT",  tmp_path / "workspace" / "leetcode")


# ── check_workspace ────────────────────────────────────────────────────────────

def test_check_workspace_reports_missing_on_fresh_clone(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    result = s.check_workspace()
    assert "config.json — MISSING" in result
    assert "setup_workspace()" in result


def test_check_workspace_reports_complete_after_setup(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    result = s.check_workspace()
    assert "Workspace looks complete" in result
    assert "config.json — present" in result


# ── setup_workspace ────────────────────────────────────────────────────────────

def test_setup_creates_all_resume_subdirs(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    for subdir in s._RESUME_SUBDIRS:
        assert (tmp_path / "workspace" / "resumes" / subdir).exists(), f"Missing: {subdir}"


def test_setup_writes_master_resume(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    mr = tmp_path / "workspace" / "resumes" / "01-Current-Optimized" / "Test User Resume - MASTER SOURCE.txt"
    assert mr.exists()
    assert "Software Engineer" in mr.read_text()


def test_setup_writes_config_json(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    cfg_path = tmp_path / "config.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text())
    assert cfg["contact"]["email"] == "test@example.com"
    assert cfg["contact"]["name"] == "Test User"
    assert "openai_api_key" not in cfg  # not provided


def test_setup_writes_config_with_openai_key(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL, openai_api_key="sk-test123")
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg.get("openai_api_key") == "sk-test123"
    assert cfg.get("openai_model") == "gpt-4o-mini"


def test_setup_creates_all_data_files(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    for fname in s._DATA_FILES:
        assert (tmp_path / "data" / fname).exists(), f"Missing data file: {fname}"


def test_setup_idempotent_does_not_overwrite_master_resume(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    mr = tmp_path / "workspace" / "resumes" / "01-Current-Optimized" / "Test User Resume - MASTER SOURCE.txt"
    mr.write_text("ORIGINAL CONTENT", encoding="utf-8")
    # Re-run setup with different content
    params = {**_MINIMAL, "master_resume_content": "REPLACEMENT CONTENT"}
    s.setup_workspace(**params)
    # Should NOT have overwritten
    assert mr.read_text() == "ORIGINAL CONTENT"


def test_setup_idempotent_does_not_overwrite_config(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    cfg_path = tmp_path / "config.json"
    original = cfg_path.read_text()
    s.setup_workspace(**{**_MINIMAL, "email": "different@example.com"})
    assert cfg_path.read_text() == original  # unchanged


def test_setup_already_exists_reported_in_skipped(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    result = s.setup_workspace(**_MINIMAL)
    assert "Already existed" in result


# ── LeetCode language scaffolding ──────────────────────────────────────────────

@pytest.mark.parametrize("lang,expected_dir,expected_file", [
    ("java",       "src/problems", "HelloWorld.java"),
    ("python",     "problems",     "hello_world.py"),
    ("javascript", "problems",     "helloWorld.js"),
    ("typescript", "problems",     "helloWorld.ts"),
    ("cpp",        "problems",     "hello_world.cpp"),
])
def test_setup_leetcode_language_scaffolding(monkeypatch, tmp_path, lang, expected_dir, expected_file):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL, leetcode_language=lang)
    lc = tmp_path / "workspace" / "leetcode"
    assert (lc / expected_dir / expected_file).exists()
    assert (lc / "Algorithm_Cheatsheet.md").exists()
    assert (lc / "Interview_Quick_Reference.md").exists()


def test_setup_invalid_language_returns_error(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    result = s.setup_workspace(**_MINIMAL, leetcode_language="ruby")
    assert "Unsupported" in result
    assert "ruby" in result


def test_setup_language_recorded_in_config(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL, leetcode_language="python")
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["leetcode_language"] == "python"
    assert cfg["leetcode_problems_dir"] == "problems"


# ── check_workspace detail ─────────────────────────────────────────────────────

def test_check_workspace_shows_master_resume_word_count(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    result = s.check_workspace()
    assert "MASTER SOURCE.txt" in result
    assert "words" in result


def test_check_workspace_shows_no_openai_when_missing(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL)
    result = s.check_workspace()
    assert "Copilot-assisted" in result


def test_check_workspace_shows_openai_when_key_set(monkeypatch, tmp_path):
    import tools.setup as s
    _patch_here(monkeypatch, tmp_path, s)
    s.setup_workspace(**_MINIMAL, openai_api_key="sk-abc")
    result = s.check_workspace()
    assert "auto-generation enabled" in result
