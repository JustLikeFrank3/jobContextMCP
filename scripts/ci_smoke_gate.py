"""CI smoke gate — Layer 1 evals against an isolated throwaway workspace.

Runs every non-network eval case (writes land in a tmp dir, mirroring
tests/conftest.py's isolated_server fixture) with fully verbose per-case
logging, then applies the release rule from docs/eval-framework.md:
**smoke pass rate < 95% exits non-zero**, failing the CI job and blocking
the deploy jobs behind it.

Validates the tool surface, not live data — the live complement is
``python -m evals layer1 --tags smoke`` against a real workspace.

Usage:  python scripts/ci_smoke_gate.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server as srv  # noqa: E402
from evals.layer1 import run_cases  # noqa: E402


def build_isolated_workspace() -> dict:
    """Create a throwaway workspace and return its config dict."""
    tmp = Path(tempfile.mkdtemp(prefix="smoke-gate-"))
    dirs = {name: tmp / name for name in ("data", "resumes", "leetcode", "side_project")}
    for d in dirs.values():
        d.mkdir(parents=True)
    (dirs["resumes"] / "master_resume.txt").write_text("[CI MASTER RESUME]", encoding="utf-8")
    (dirs["leetcode"] / "cheatsheet.md").write_text("[CI CHEATSHEET]", encoding="utf-8")
    (dirs["leetcode"] / "quick_ref.md").write_text("[CI QUICK REFERENCE]", encoding="utf-8")
    for name in ("template_format.txt", "achievements.txt",
                 "feedback_received.txt", "skills_shorter.txt"):
        (dirs["resumes"] / name).write_text(f"[CI {name}]", encoding="utf-8")
    # _load_master_context resolves achievements/feedback from the workspace's
    # 06-Reference-Materials/ dir — TC-002 asserts the enrichment block renders.
    ref_dir = dirs["resumes"] / "06-Reference-Materials"
    ref_dir.mkdir()
    (ref_dir / "achievements.txt").write_text("[CI ACHIEVEMENTS CONTENT]", encoding="utf-8")
    (ref_dir / "feedback_received.txt").write_text("[CI FEEDBACK CONTENT]", encoding="utf-8")
    (dirs["data"] / "status.json").write_text(
        json.dumps({"applications": [], "pipeline_summary": "CI"}), encoding="utf-8"
    )
    return {
        "resume_folder": str(dirs["resumes"]),
        "leetcode_folder": str(dirs["leetcode"]),
        "side_project_folders": [str(dirs["side_project"])],
        "data_folder": str(dirs["data"]),
        "master_resume_path": "master_resume.txt",
        "leetcode_cheatsheet_path": "cheatsheet.md",
        "quick_reference_path": "quick_ref.md",
        "template_format_path": "template_format.txt",
        "achievements_path": "achievements.txt",
        "feedback_received_path": "feedback_received.txt",
        "skills_shorter_path": "skills_shorter.txt",
    }


def main() -> int:
    banner = "═" * 63
    print(banner)
    print("  LAYER 1 SMOKE GATE — <95% smoke pass rate blocks this deploy")
    print(banner)
    srv._reconfigure(build_isolated_workspace())
    report = run_cases()  # all non-network cases; writes hit the tmp workspace
    print(report.to_text(verbose=True))
    print()
    if report.release_blocked():
        print(
            f"✗ SMOKE GATE FAILED — smoke pass rate {report.smoke_pass_rate():.0%} "
            "< 95%. Deploy blocked."
        )
        return 1
    print(
        f"✓ SMOKE GATE PASSED — smoke {report.smoke_pass_rate():.0%}, "
        f"overall {report.pass_rate:.0%} "
        f"({sum(r.ok for r in report.results)}/{len(report.results)}), "
        f"p95 {report.latency_percentile(95):.1f} ms"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
