"""Tests for scripts/update_readme_badges.py.

Covers the JUnit test-count parser, the README badge rewriter, and the bundled
LaTeX resume section updater that keeps the resume bullet's live test/tool
counts in sync with the README badges.
"""
import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_readme_badges.py"
_spec = importlib.util.spec_from_file_location("update_readme_badges", _SCRIPT)
assert _spec is not None and _spec.loader is not None
badges = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(badges)


# ---------------------------------------------------------------------------
# passing_tests
# ---------------------------------------------------------------------------

def test_passing_tests_subtracts_non_passing(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="10" failures="1" errors="1" skipped="2"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert badges.passing_tests(junit) == 6


def test_passing_tests_sums_multiple_suites(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        "<testsuites>"
        '<testsuite tests="5" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="7" failures="1" errors="0" skipped="1"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert badges.passing_tests(junit) == 5 + 5


# ---------------------------------------------------------------------------
# coverage_pct
# ---------------------------------------------------------------------------

def test_coverage_pct_formats_two_decimals(tmp_path):
    cov = tmp_path / "coverage.xml"
    cov.write_text('<coverage line-rate="0.8231"></coverage>', encoding="utf-8")
    assert badges.coverage_pct(cov) == "82.31"


# ---------------------------------------------------------------------------
# update_resume_section
# ---------------------------------------------------------------------------

def test_update_resume_section_rewrites_test_and_tool_counts():
    src = (
        r"\item Stood up a CI pipeline ...; hold 931 passing tests at 80\%+ "
        r"line coverage through disciplined TDD." "\n"
        r"\item Engineered an LLM agent layer (... exposing 80 tools) with ..."
    )
    out = badges.update_resume_section(src, 1214, 85)
    assert "hold 1214 passing tests" in out
    assert "exposing 85 tools" in out
    # Stale numbers are gone.
    assert "931 passing tests" not in out
    assert "exposing 80 tools" not in out


def test_update_resume_section_preserves_coverage_prose():
    """Coverage stays evergreen prose — the updater must not touch it."""
    src = r"hold 100 passing tests at 80\%+ line coverage through disciplined TDD."
    out = badges.update_resume_section(src, 1214, 85)
    assert r"80\%+ line coverage" in out


def test_update_resume_section_no_match_returns_unchanged():
    src = "nothing quantified here"
    assert badges.update_resume_section(src, 1214, 85) == src


# ---------------------------------------------------------------------------
# update_readme
# ---------------------------------------------------------------------------

def test_update_readme_rewrites_test_and_tool_badges():
    src = (
        'badge/tests-1%20passing-brightgreen alt="1 tests passing" '
        'badge/tools-1-informational alt="1 MCP tools"'
    )
    out = badges.update_readme(src, 1214, 85)
    assert "badge/tests-1214%20passing-" in out
    assert 'alt="1214 tests passing"' in out
    assert "badge/tools-85-" in out
    assert 'alt="85 MCP tools"' in out


# ---------------------------------------------------------------------------
# main() end-to-end wiring
# ---------------------------------------------------------------------------

def test_main_updates_both_readme_and_resume_section(tmp_path, monkeypatch):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="1214" failures="0" errors="0" skipped="0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    cov = tmp_path / "coverage.xml"
    cov.write_text('<coverage line-rate="0.823"></coverage>', encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        'badge/tests-1%20passing-brightgreen alt="1 tests passing" '
        'badge/tools-1-informational alt="1 MCP tools"',
        encoding="utf-8",
    )
    section = tmp_path / "experience.tex"
    section.write_text(
        r"hold 1 passing tests at 80\%+ line coverage; exposing 1 tools) done.",
        encoding="utf-8",
    )

    monkeypatch.setattr(badges, "tool_count", lambda: 85)
    monkeypatch.setattr(
        sys, "argv",
        ["update_readme_badges.py", "--junit", str(junit), "--coverage", str(cov),
         "--readme", str(readme), "--resume-section", str(section)],
    )

    rc = badges.main()

    assert rc == 0
    readme_out = readme.read_text(encoding="utf-8")
    assert "badge/tests-1214%20passing-" in readme_out
    assert "badge/tools-85-" in readme_out
    section_out = section.read_text(encoding="utf-8")
    assert "hold 1214 passing tests" in section_out
    assert "exposing 85 tools" in section_out


def test_main_skips_resume_section_when_missing(tmp_path, monkeypatch):
    """A missing resume-section path must not crash main()."""
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="5" failures="0" errors="0" skipped="0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    cov = tmp_path / "coverage.xml"
    cov.write_text('<coverage line-rate="0.5"></coverage>', encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("badge/tests-1%20passing- badge/tools-1-", encoding="utf-8")

    monkeypatch.setattr(badges, "tool_count", lambda: 85)
    monkeypatch.setattr(
        sys, "argv",
        ["update_readme_badges.py", "--junit", str(junit), "--coverage", str(cov),
         "--readme", str(readme),
         "--resume-section", str(tmp_path / "does_not_exist.tex")],
    )

    assert badges.main() == 0
