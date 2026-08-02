"""Tests for scripts/update_readme_badges.py.

Covers the JUnit test-count parser, the README badge rewriter, and the bundled
LaTeX resume section updater that keeps the resume bullet's live test/tool
counts in sync with the README badges.

The tests in the "real files" section are the drift alarm: they run every
managed pattern against the actual README.md and experience.tex. When a badge
is reshaped by hand (as the tools badge was, silently, in a97f892) the matching
test fails by name instead of the generator emitting a warning nobody reads.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "update_readme_badges.py"
_README = _REPO_ROOT / "README.md"
_RESUME_SECTION = _REPO_ROOT / "templates" / "latex_assets" / "sections" / "experience.tex"

_spec = importlib.util.spec_from_file_location("update_readme_badges", _SCRIPT)
assert _spec is not None and _spec.loader is not None
badges = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(badges)


def _readme_fixture(tests: int = 1, tools: int = 1, actions: int = 1) -> str:
    """A synthetic README carrying every shape the updater manages.

    Kept honest by test_fixture_covers_every_managed_readme_pattern — if a
    pattern is added to the script, this fixture must grow with it.
    """
    return "\n".join([
        f'<img src="https://img.shields.io/badge/tests-{tests}%20passing-brightgreen"'
        f' alt="{tests} tests passing"/>',
        f'<img src="https://img.shields.io/badge/tools-{tools}%20domains%20%C2%B7%20'
        f'{actions}%20actions-informational" alt="{tools} domain tools, {actions} actions"/>',
        f"| {tools} MCP tools | {actions} domain actions behind them |",
        f"| {tests} passing tests | Resume + cover letter generation |",
        f'        TOOLS["{tools} MCP / CLI tools"]',
        f"# Expected: OK, {tools} tools",
        f"the Output pane should show `Discovered {tools} tools`.",
    ])


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
# action_count
# ---------------------------------------------------------------------------

def test_action_count_sums_the_domain_specs():
    """Pins the source of the badge's action number to the facade specs.

    importorskip so the module stays runnable without the full app env; CI has
    the deps, which is where the badge is actually generated.
    """
    consolidated = pytest.importorskip("tools.consolidated")
    expected = sum(len(actions) for actions in consolidated.DOMAINS.values())
    assert badges.action_count() == expected
    assert expected > len(consolidated.DOMAINS)


# ---------------------------------------------------------------------------
# update_resume_section
# ---------------------------------------------------------------------------

def test_update_resume_section_rewrites_test_count():
    src = (
        r"\item Built and maintained a CI pipeline ...; hold 931 passing tests "
        r"at 80\%+ line coverage through disciplined TDD."
    )
    out = badges.update_resume_section(src, 1214)
    assert "hold 1214 passing tests" in out
    # Stale number is gone.
    assert "931 passing tests" not in out


def test_update_resume_section_preserves_coverage_prose():
    """Coverage stays evergreen prose — the updater must not touch it."""
    src = r"hold 100 passing tests at 80\%+ line coverage through disciplined TDD."
    out = badges.update_resume_section(src, 1214)
    assert r"80\%+ line coverage" in out


def test_update_resume_section_no_match_raises():
    """A reworded bullet must fail the job, not silently skip the update."""
    with pytest.raises(badges.BadgePatternError) as exc:
        badges.update_resume_section("nothing quantified here", 1214)
    assert exc.value.missing == ["resume passing tests"]


# ---------------------------------------------------------------------------
# update_readme
# ---------------------------------------------------------------------------

def test_update_readme_rewrites_every_managed_number():
    out = badges.update_readme(_readme_fixture(), 1214, 12, 96)

    assert "badge/tests-1214%20passing-" in out
    assert 'alt="1214 tests passing"' in out
    assert "badge/tools-12%20domains%20%C2%B7%2096%20actions-" in out
    assert 'alt="12 domain tools, 96 actions"' in out
    assert "| 12 MCP tools | 96 domain actions behind them |" in out
    assert "| 1214 passing tests |" in out
    assert 'TOOLS["12 MCP / CLI tools"]' in out
    assert "# Expected: OK, 12 tools" in out
    assert "Discovered 12 tools" in out
    # No placeholder survives anywhere.
    assert "1 MCP tools" not in out


def test_update_readme_raises_when_a_pattern_stops_matching():
    """The tools badge reshaped by hand — the exact a97f892 regression."""
    reshaped = _readme_fixture().replace(
        "badge/tools-1%20domains%20%C2%B7%201%20actions-informational",
        "badge/tools-1%20facades-informational",
    )
    with pytest.raises(badges.BadgePatternError) as exc:
        badges.update_readme(reshaped, 1214, 12, 96)
    assert exc.value.missing == ["tools badge"]
    assert "tools badge" in str(exc.value)


def test_update_readme_reports_every_missing_pattern_at_once():
    with pytest.raises(badges.BadgePatternError) as exc:
        badges.update_readme("no managed strings here", 1214, 12, 96)
    labels = [label for label, _, _ in badges.readme_substitutions(1214, 12, 96)]
    assert exc.value.missing == labels


def test_fixture_covers_every_managed_readme_pattern():
    """Guards the fixture itself: a new pattern must be represented here."""
    src = _readme_fixture()
    for label, pattern, _ in badges.readme_substitutions(1, 1, 1):
        assert re.search(pattern, src), f"fixture is missing a case for: {label}"


# ---------------------------------------------------------------------------
# Real files — pins the shipped README / resume shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,pattern",
    [(label, pattern) for label, pattern, _ in badges.readme_substitutions(1, 1, 1)],
)
def test_real_readme_still_matches_pattern(label, pattern):
    """Every managed README string is still in the shape the generator expects.

    If this fails, README.md was reformatted: update the matching entry in
    readme_substitutions() rather than leaving the number hand-maintained.
    """
    src = _README.read_text(encoding="utf-8")
    assert re.search(pattern, src), f"README.md no longer matches the '{label}' pattern"


@pytest.mark.parametrize(
    "label,pattern",
    [(label, pattern) for label, pattern, _ in badges.resume_substitutions(1)],
)
def test_real_resume_section_still_matches_pattern(label, pattern):
    src = _RESUME_SECTION.read_text(encoding="utf-8")
    assert re.search(pattern, src), f"experience.tex no longer matches the '{label}' pattern"


def test_real_readme_round_trips_through_the_updater():
    """End-to-end on the shipped README: no pattern misses, numbers land."""
    src = _README.read_text(encoding="utf-8")
    out = badges.update_readme(src, 4242, 7, 33)

    assert "badge/tests-4242%20passing-" in out
    assert "badge/tools-7%20domains%20%C2%B7%2033%20actions-" in out
    assert 'alt="7 domain tools, 33 actions"' in out
    assert "| 7 MCP tools | 33 domain actions behind them |" in out


def test_real_readme_tools_badge_and_tldr_row_agree():
    """The badge and the TL;DR row quote the same two numbers.

    They are separate substitutions, so a half-applied rewrite would leave the
    README internally inconsistent without any pattern missing.
    """
    src = _README.read_text(encoding="utf-8")
    badge = re.search(r"badge/tools-(\d+)%20domains%20%C2%B7%20(\d+)%20actions-", src)
    row = re.search(r"\| (\d+) MCP tools \| (\d+) domain actions behind them \|", src)
    assert badge and row
    assert badge.groups() == row.groups()


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
    readme.write_text(_readme_fixture(), encoding="utf-8")
    section = tmp_path / "experience.tex"
    section.write_text(
        r"hold 1 passing tests at 80\%+ line coverage through disciplined TDD.",
        encoding="utf-8",
    )

    monkeypatch.setattr(badges, "tool_count", lambda: 12)
    monkeypatch.setattr(badges, "action_count", lambda: 96)
    monkeypatch.setattr(
        sys, "argv",
        ["update_readme_badges.py", "--junit", str(junit), "--coverage", str(cov),
         "--readme", str(readme), "--resume-section", str(section)],
    )

    rc = badges.main()

    assert rc == 0
    readme_out = readme.read_text(encoding="utf-8")
    assert "badge/tests-1214%20passing-" in readme_out
    assert "badge/tools-12%20domains%20%C2%B7%2096%20actions-" in readme_out
    section_out = section.read_text(encoding="utf-8")
    assert "hold 1214 passing tests" in section_out


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
    readme.write_text(_readme_fixture(), encoding="utf-8")

    monkeypatch.setattr(badges, "tool_count", lambda: 12)
    monkeypatch.setattr(badges, "action_count", lambda: 96)
    monkeypatch.setattr(
        sys, "argv",
        ["update_readme_badges.py", "--junit", str(junit), "--coverage", str(cov),
         "--readme", str(readme),
         "--resume-section", str(tmp_path / "does_not_exist.tex")],
    )

    assert badges.main() == 0


def _main_argv(tmp_path, readme, section=None):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="9" failures="0" errors="0" skipped="0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    cov = tmp_path / "coverage.xml"
    cov.write_text('<coverage line-rate="0.9"></coverage>', encoding="utf-8")
    argv = ["update_readme_badges.py", "--junit", str(junit), "--coverage", str(cov),
            "--readme", str(readme)]
    if section is not None:
        argv += ["--resume-section", str(section)]
    return argv


def test_main_fails_the_job_when_a_readme_pattern_drifts(tmp_path, monkeypatch, capsys):
    """A no-match must exit non-zero — a skipped badge is how drift hid before."""
    readme = tmp_path / "README.md"
    stale = _readme_fixture().replace(
        "badge/tools-1%20domains%20%C2%B7%201%20actions-informational",
        "badge/tools-1-informational",
    )
    readme.write_text(stale, encoding="utf-8")

    monkeypatch.setattr(badges, "tool_count", lambda: 12)
    monkeypatch.setattr(badges, "action_count", lambda: 96)
    monkeypatch.setattr(sys, "argv", _main_argv(tmp_path, readme, tmp_path / "missing.tex"))

    assert badges.main() == 1
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "tools badge" in err
    # Nothing half-written: the drifted README is left exactly as found.
    assert readme.read_text(encoding="utf-8") == stale


def test_main_fails_when_the_resume_bullet_drifts(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(_readme_fixture(), encoding="utf-8")
    section = tmp_path / "experience.tex"
    section.write_text("no quantified bullet here", encoding="utf-8")

    monkeypatch.setattr(badges, "tool_count", lambda: 12)
    monkeypatch.setattr(badges, "action_count", lambda: 96)
    monkeypatch.setattr(sys, "argv", _main_argv(tmp_path, readme, section))

    assert badges.main() == 1
    assert "resume passing tests" in capsys.readouterr().err
    # The README half of the run still applied — only the drifted target failed.
    assert "Discovered 12 tools" in readme.read_text(encoding="utf-8")
