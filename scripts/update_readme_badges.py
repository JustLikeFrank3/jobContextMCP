#!/usr/bin/env python3
"""
Regenerate the README status badges (tests / coverage / tools) and the matching
inline stats from real measurements, so they never drift from the suite again.

Sources of truth:
  • tests    — passing count from a JUnit XML report (tests - failures - errors - skipped)
  • coverage — line-rate from coverage.xml (Cobertura format)
  • tools    — len(server.mcp._tool_manager.list_tools()) at runtime

Usage:
    python scripts/update_readme_badges.py \
        --junit junit.xml --coverage coverage.xml --readme README.md

Exits 0 whether or not anything changed; prints a one-line summary. Designed to
run in CI after the test job, with the result committed back via [skip ci].
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


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


def tool_count() -> int:
    # Ensure the project root is importable regardless of CWD (the script lives
    # in scripts/, which otherwise shadows the repo root on sys.path).
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import server  # imported lazily so the script is usable without a full env

    return len(server.mcp._tool_manager.list_tools())


def update_readme(text: str, tests: int, tools: int) -> str:
    """Apply anchored substitutions. Each pattern is specific enough that a miss
    means the README format changed and the caller should be alerted."""
    subs: list[tuple[str, str, str]] = [
        # ── Badges (shields.io) ──────────────────────────────────────────────
        ("tests badge",
         r"badge/tests-\d+%20passing-",
         f"badge/tests-{tests}%20passing-"),
        ("tests badge alt",
         r'alt="\d+ tests passing"',
         f'alt="{tests} tests passing"'),
        # Coverage is shown via a live SonarCloud measure badge (see README),
        # so it is intentionally not managed here — no static badge to rewrite.
        ("tools badge",
         r"badge/tools-\d+-",
         f"badge/tools-{tools}-"),
        ("tools badge alt",
         r'alt="\d+ MCP tools"',
         f'alt="{tools} MCP tools"'),
        # ── Inline current-state stats ───────────────────────────────────────
        ("TL;DR tools row",
         r"\| \d+ MCP tools \|",
         f"| {tools} MCP tools |"),
        ("TL;DR tests row",
         r"\| \d+ passing tests \|",
         f"| {tests} passing tests |"),
        ("CLI 'all N tools'",
         r"invokes all \d+ tools directly",
         f"invokes all {tools} tools directly"),
        ("CLI 'any of the N tools'",
         r"Invoke any of the \d+ tools directly",
         f"Invoke any of the {tools} tools directly"),
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

    missing: list[str] = []
    for label, pattern, repl in subs:
        text, n = re.subn(pattern, repl, text)
        if n == 0:
            missing.append(label)

    if missing:
        # Non-fatal: prose may legitimately be reworded. Warn so it's visible in
        # CI logs without breaking the deploy.
        print(f"::warning::README badge updater found no match for: {', '.join(missing)}",
              file=sys.stderr)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", type=Path, default=Path("junit.xml"))
    ap.add_argument("--coverage", type=Path, default=Path("coverage.xml"))
    ap.add_argument("--readme", type=Path, default=Path("README.md"))
    args = ap.parse_args()

    tests = passing_tests(args.junit)
    coverage = coverage_pct(args.coverage)
    tools = tool_count()

    original = args.readme.read_text(encoding="utf-8")
    updated = update_readme(original, tests, tools)

    if updated == original:
        print(f"README badges already current: {tests} tests, {coverage}% coverage, {tools} tools")
    else:
        args.readme.write_text(updated, encoding="utf-8")
        print(f"README badges updated: {tests} tests, {coverage}% coverage, {tools} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
