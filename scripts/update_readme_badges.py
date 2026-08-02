#!/usr/bin/env python3
"""
Regenerate the README status badges (tests / coverage / tools) and the matching
inline stats from real measurements, so they never drift from the suite again.
The bundled LaTeX sample resume's CI bullet is kept in sync from the same JUnit
source (passing-test count).

Sources of truth:
  • tests    — passing count from a JUnit XML report (tests - failures - errors - skipped)
  • coverage — line-rate from coverage.xml (Cobertura format)
  • tools    — len(server.mcp._tool_manager.list_tools()) at runtime
  • actions  — total dispatch actions across tools.consolidated.DOMAINS

Usage:
    python scripts/update_readme_badges.py \
        --junit junit.xml --coverage coverage.xml --readme README.md \
        --resume-section templates/latex_assets/sections/experience.tex

Exits 0 whether or not anything changed; prints a one-line summary. A managed
pattern that no longer matches is a HARD FAILURE (exit 1, ``::error::``
annotation) — a silently skipped badge is how the tools badge drifted for
weeks after its format changed. If a README/resume edit intentionally reshapes
a managed string, update the matching pattern here in the same change; the
tests in tests/test_update_readme_badges.py pin every shape against the real
files so the break surfaces before CI. Designed to run in CI after the test
job, with the result committed back via [skip ci].
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Bundled LaTeX resume experience section whose jobContext bullet cites the
#: live test/tool counts. Kept in sync with the README badges from the same
#: JUnit / runtime sources so the resume never quotes a stale number.
RESUME_SECTION_DEFAULT = Path("templates/latex_assets/sections/experience.tex")


class BadgePatternError(RuntimeError):
    """A managed substitution pattern matched nothing.

    Raised instead of warning: the point of the generator is that the quoted
    numbers cannot drift, so an unmatched pattern must break the job loudly.
    """

    def __init__(self, target: str, missing: list[str]) -> None:
        self.target = target
        self.missing = list(missing)
        super().__init__(
            f"{target} updater found no match for: {', '.join(self.missing)}"
        )


def _apply(target: str, text: str, subs: list[tuple[str, str, str]]) -> str:
    """Apply every substitution, raising if any pattern matched nothing."""
    missing: list[str] = []
    for label, pattern, repl in subs:
        text, n = re.subn(pattern, repl, text)
        if n == 0:
            missing.append(label)
    if missing:
        raise BadgePatternError(target, missing)
    return text


def passing_tests(junit_path: Path) -> int:
    """Sum across <testsuite> elements: tests - failures - errors - skipped."""
    root = ET.parse(junit_path).getroot()
    suites = root.iter("testsuite")
    total = 0
    for s in suites:
        g = lambda k: int(s.get(k, "0") or "0")
        total += g("tests") - g("failures") - g("errors") - g("skipped")
    return total


def coverage_pct(coverage_path: Path) -> str:
    """Two-decimal percentage from the Cobertura line-rate attribute."""
    root = ET.parse(coverage_path).getroot()
    rate = float(root.get("line-rate", "0"))
    return f"{rate * 100:.2f}"


def _add_repo_root_to_path() -> None:
    """Make the project root importable regardless of CWD (the script lives in
    scripts/, which otherwise shadows the repo root on sys.path)."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


def tool_count() -> int:
    _add_repo_root_to_path()
    import server  # imported lazily so the script is usable without a full env

    return len(server.mcp._tool_manager.list_tools())


def action_count() -> int:
    """Total dispatch actions behind the consolidated domain facades.

    The tools badge quotes both numbers ("12 domains · 96 actions"), and the
    action count moves whenever a row is added to a domain spec — exactly the
    kind of number that goes stale by hand.
    """
    _add_repo_root_to_path()
    from tools.consolidated import DOMAINS  # lazy, same reason as tool_count

    return sum(len(actions) for actions in DOMAINS.values())


def readme_substitutions(tests: int, tools: int, actions: int) -> list[tuple[str, str, str]]:
    """The (label, pattern, replacement) triples the README updater applies.

    Exposed so the test suite can pin every pattern against the real README —
    a format change then fails a named test instead of going quiet.
    """
    return [
        # ── Badges (shields.io) ──────────────────────────────────────────────
        ("tests badge",
         r"badge/tests-\d+%20passing-",
         f"badge/tests-{tests}%20passing-"),
        ("tests badge alt",
         r'alt="\d+ tests passing"',
         f'alt="{tests} tests passing"'),
        # Coverage is shown via a live SonarCloud measure badge (see README),
        # so it is intentionally not managed here — no static badge to rewrite.
        # The tools badge carries both counts: "tools-12 domains · 96 actions"
        # (%C2%B7 is the URL-encoded middot).
        ("tools badge",
         r"badge/tools-\d+%20domains%20%C2%B7%20\d+%20actions-",
         f"badge/tools-{tools}%20domains%20%C2%B7%20{actions}%20actions-"),
        ("tools badge alt",
         r'alt="\d+ domain tools, \d+ actions"',
         f'alt="{tools} domain tools, {actions} actions"'),
        # ── Inline current-state stats ───────────────────────────────────────
        ("TL;DR tools row",
         r"\| \d+ MCP tools \|",
         f"| {tools} MCP tools |"),
        ("TL;DR actions cell",
         r"\| \d+ domain actions behind them \|",
         f"| {actions} domain actions behind them |"),
        ("TL;DR tests row",
         r"\| \d+ passing tests \|",
         f"| {tests} passing tests |"),
        # The CLI section deliberately quotes no tool count — cli.py exposes the
        # legacy per-function surface, not the {tools}-facade MCP surface, so a
        # single auto-written number there would always be wrong for one of them.
        ("diagram subgraph label",
         r'TOOLS\["\d+ MCP / CLI tools"\]',
         f'TOOLS["{tools} MCP / CLI tools"]'),
        ("smoke-test expected",
         r"# Expected: OK, \d+ tools",
         f"# Expected: OK, {tools} tools"),
        ("discovered N tools",
         r"Discovered \d+ tools",
         f"Discovered {tools} tools"),
    ]


def update_readme(text: str, tests: int, tools: int, actions: int) -> str:
    """Apply anchored substitutions. Each pattern is specific enough that a miss
    means the README format changed, so a miss raises BadgePatternError."""
    return _apply("README badge", text, readme_substitutions(tests, tools, actions))


def resume_substitutions(tests: int) -> list[tuple[str, str, str]]:
    """The (label, pattern, replacement) triples the resume updater applies."""
    return [
        ("resume passing tests",
         r"hold \d+ passing tests",
         f"hold {tests} passing tests"),
    ]


def update_resume_section(text: str, tests: int) -> str:
    """Rewrite the sample resume bullet's live passing-test count in-place.

    Uses the same measured value as the README tests badge so the bundled
    sample template never quotes a stale number. Coverage is deliberately left
    as evergreen prose (e.g. "80%+ line coverage") to avoid drift, and the tool
    count is a README-only concern (too product-specific for a generic resume).

    Raises BadgePatternError if the bullet no longer matches — same contract as
    update_readme.
    """
    return _apply("resume section", text, resume_substitutions(tests))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", type=Path, default=Path("junit.xml"))
    ap.add_argument("--coverage", type=Path, default=Path("coverage.xml"))
    ap.add_argument("--readme", type=Path, default=Path("README.md"))
    ap.add_argument("--resume-section", type=Path, default=RESUME_SECTION_DEFAULT,
                    help="LaTeX resume experience section to keep in sync (blank to skip).")
    args = ap.parse_args()

    tests = passing_tests(args.junit)
    coverage = coverage_pct(args.coverage)
    tools = tool_count()
    actions = action_count()

    summary = (f"{tests} tests, {coverage}% coverage, "
               f"{tools} tools, {actions} actions")

    # Both targets are attempted even if the first drifts, so one run reports
    # every stale pattern instead of trickling them out across CI runs.
    failures: list[BadgePatternError] = []

    original = args.readme.read_text(encoding="utf-8")
    try:
        updated = update_readme(original, tests, tools, actions)
    except BadgePatternError as exc:
        failures.append(exc)
    else:
        if updated == original:
            print(f"README badges already current: {summary}")
        else:
            args.readme.write_text(updated, encoding="utf-8")
            print(f"README badges updated: {summary}")

    # Keep the bundled sample resume bullet's test count in sync from JUnit.
    section_path = args.resume_section
    if section_path and Path(section_path).exists():
        section_orig = Path(section_path).read_text(encoding="utf-8")
        try:
            section_new = update_resume_section(section_orig, tests)
        except BadgePatternError as exc:
            failures.append(exc)
        else:
            if section_new == section_orig:
                print(f"Resume section already current: {tests} tests")
            else:
                Path(section_path).write_text(section_new, encoding="utf-8")
                print(f"Resume section updated: {tests} tests")

    if failures:
        for exc in failures:
            print(f"::error::{exc}", file=sys.stderr)
        print("::error::Managed strings drifted from their patterns — update "
              "scripts/update_readme_badges.py so the numbers stay generated.",
              file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
