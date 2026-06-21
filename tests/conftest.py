"""
Shared fixtures for JobContextMCP test suite.

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
        side_project/       ← SIDE_PROJECT_FOLDER stub

    Yields the tmp_path root.  After the test, globals are restored to their
    original production values so other tests are unaffected.
    """
    data_dir  = tmp_path / "data"
    res_dir   = tmp_path / "resumes"
    lc_dir    = tmp_path / "leetcode"
    sc_dir    = tmp_path / "side_project"
    for d in (data_dir, res_dir, lc_dir, sc_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Stub files so _read() calls don't blow up
    _write(res_dir / "master_resume.txt", "[TEST MASTER RESUME]")
    _write(lc_dir  / "cheatsheet.md",     "[TEST CHEATSHEET]")
    _write(lc_dir  / "quick_ref.md",      "[TEST QUICK REFERENCE]")
    # Stub reference files required by _reconfigure
    _write(res_dir / "template_format.txt",    "[TEST TEMPLATE FORMAT]")
    _write(res_dir / "achievements.txt",      "[TEST ACHIEVEMENTS]")
    _write(res_dir / "feedback_received.txt",   "[TEST FEEDBACK]")
    _write(res_dir / "skills_shorter.txt",      "[TEST SKILLS]")

    # Minimal status so get_job_hunt_status() has something to read
    _write_json(data_dir / "status.json", {"applications": [], "pipeline_summary": "TEST"})

    # Minimal personal context — metrics and framing required by STAR context tests.
    # Values are generic synthetic test data; they must satisfy the numeric/keyword
    # assertions in test_star_context.py without encoding any real user information.
    _write_json(data_dir / "personal_context.json", {
        "stories": [],
        "star_metrics": {
            "testing":        ["80%+ test coverage across unit, integration, and end-to-end suites"],
            "quality":        ["98% SLA on production service throughout all migration phases"],
            "craftsmanship":  ["TDD enforced from first commit — no QA buffer to fall back on"],
            "solo-developer": ["Sole developer across 500K+ line codebase with no feature freeze"],
            "cloud":          ["On-prem to Azure Container Apps migration with zero downtime"],
            "ai":             ["Drove 35%+ AI tooling adoption across the engineering org"],
            "leadership":     ["Led cross-functional initiatives without formal authority"],
            "modernization":  ["Major framework upgrade across 500K+ lines, no regressions"],
            "ford":           ["Family legacy in manufacturing — quality built in, not bolted on"],
        },
        "company_framing": {
            "ford": {
                "legacy": "50-year family legacy in automotive manufacturing — quality as an inherited value",
                "angle":  "Quality built in from the ground up, not added as an afterthought",
            },
            "fanduel": {
                "values": "Scale, speed, and uptime under real-time load",
                "angle":  "Testing rigor is what lets you ship fast without eroding trust",
            },
        },
    })

    fake_cfg = {
        "resume_folder":              str(res_dir),
        "leetcode_folder":            str(lc_dir),
        "side_project_folders":        [str(sc_dir)],
        "data_folder":                str(data_dir),
        "master_resume_path":         "master_resume.txt",
        "leetcode_cheatsheet_path":   "cheatsheet.md",
        "quick_reference_path":       "quick_ref.md",
        "resume_template_png":        "resume_template.png",
        "cover_letter_template_png":  "cover_letter_template.png",
        "template_format_path":       "template_format.txt",
        "achievements_path":           "achievements.txt",
        "feedback_received_path":     "feedback_received.txt",
        "skills_shorter_path":        "skills_shorter.txt",
    }

    # Capture original globals so we can restore them
    original_cfg = {
        "resume_folder":              str(srv.RESUME_FOLDER),
        "leetcode_folder":            str(srv.LEETCODE_FOLDER),
        "side_project_folders":        [str(f) for f in srv.SIDE_PROJECT_FOLDERS],
        "data_folder":                str(srv.DATA_FOLDER),
        "master_resume_path":         srv.MASTER_RESUME.name,
        "leetcode_cheatsheet_path":   srv.LEETCODE_CHEATSHEET.name,
        "quick_reference_path":       srv.QUICK_REFERENCE.name,
        "resume_template_png":        srv.RESUME_TEMPLATE_PNG.name,
        "cover_letter_template_png":  srv.COVER_LETTER_TEMPLATE_PNG.name,
        "template_format_path":       srv.TEMPLATE_FORMAT.name,
        "achievements_path":           srv.ACHIEVEMENTS.name,
        "feedback_received_path":     srv.FEEDBACK_RECEIVED.name,
        "skills_shorter_path":        srv.SKILLS_SHORTER.name,
    }

    srv._reconfigure(fake_cfg)
    yield tmp_path
    srv._reconfigure(original_cfg)


# ──────────────────────────────────────────────────────────────────────────────
# HTTP transport fixtures (shared across HTTP/persona/workflow test modules)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def http_client_noauth(monkeypatch, isolated_server):
    """FastAPI TestClient with API_KEY unset (auth disabled)."""
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_REMOTE", raising=False)
    reset_settings_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_settings_cache()


@pytest.fixture()
def http_client_authed(monkeypatch, isolated_server):
    """FastAPI TestClient with API_KEY set to 'test-key'."""
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.delenv("ENABLE_REMOTE", raising=False)
    reset_settings_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_settings_cache()


# ──────────────────────────────────────────────────────────────────────────────
# LLM mock — prevents every test from hitting live Ollama/OpenAI
# ──────────────────────────────────────────────────────────────────────────────

_FAKE_RESUME = "FAKE RESUME CONTENT"
_FAKE_COVER = "FAKE COVER LETTER CONTENT"


@pytest.fixture(autouse=True)
def _mock_llm(request, monkeypatch):
    """Stub out LLM generate calls for all tests unless marked live_llm.

    Also forces get_llm_client() to return (None, None) so the fitment /
    assessment path (run_job_assessment, evaluate_queued_job, JobAnalysisService)
    takes its deterministic offline context-pack fallback instead of making a
    live OpenAI/Ollama request. Without this, those tests silently hit the real
    API and pass or fail depending on network/rate-limit state.

    Tests that genuinely need the live-LLM code path (with their own mocked
    client) opt out via @pytest.mark.live_llm.
    """
    if request.node.get_closest_marker("live_llm"):
        yield
        return
    monkeypatch.setattr("tools.generate.generate_resume", lambda *a, **kw: _FAKE_RESUME)
    monkeypatch.setattr("tools.generate.generate_cover_letter", lambda *a, **kw: _FAKE_COVER)
    monkeypatch.setattr("lib.config.get_llm_client", lambda task="": (None, None))
    try:
        import workflows.langgraph.resume_graph as rg
        monkeypatch.setattr(rg, "generate_resume", lambda *a, **kw: _FAKE_RESUME)
    except (ImportError, AttributeError):
        pass
    yield
