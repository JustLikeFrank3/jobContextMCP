"""CLI for the eval framework.

    python -m evals layer1 [--tags smoke] [--include-writes] [--json PATH]
    python -m evals judge --jd FILE --output FILE [--master FILE] [-n N]
    python -m evals suite [-n 5] [--entries GD-01,GD-03]

``layer1`` runs against the ACTIVE workspace. Write-tagged cases are
excluded unless ``--include-writes`` is passed — only use that in an
isolated test-user namespace, never against live data.

``judge`` scores an existing output file N times (judge-stability check).
``suite`` is the full generate→judge→variance loop over the golden dataset
and needs a configured LLM provider plus the golden files in the workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_layer1(args: argparse.Namespace) -> int:
    from evals.layer1 import run_cases

    include = tuple(args.tags.split(",")) if args.tags else None
    exclude = ("network",) if args.include_writes else ("network", "write")
    report = run_cases(include_tags=include, exclude_tags=exclude)
    print(report.to_text())
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nJSON report → {args.json}")
    return 1 if report.release_blocked() else 0


def _cmd_judge(args: argparse.Namespace) -> int:
    from evals.judge import judge_output
    from evals.variance import aggregate_runs

    jd = Path(args.jd).read_text(encoding="utf-8")
    output = Path(args.output).read_text(encoding="utf-8")
    if args.master:
        master = Path(args.master).read_text(encoding="utf-8")[:6000]
    else:
        from tools import resume

        master = resume.read_master_resume()[:6000]
    scores = []
    for i in range(args.n):
        score = judge_output(jd, master, output)
        print(f"run {i + 1}/{args.n}: mean {score.mean:.2f} verdict {score.verdict} "
              f"hallucinations {len(score.hallucinations)}")
        scores.append(score)
    agg = aggregate_runs(scores)
    print(json.dumps(agg.to_dict(), indent=2))
    return 0


def _cmd_suite(args: argparse.Namespace) -> int:
    from evals.golden import load_golden
    from evals.runner import format_dashboard, run_suite

    entries = load_golden()
    if args.entries:
        wanted = set(args.entries.split(","))
        entries = [e for e in entries if e.id in wanted]
    suite = run_suite(entries=entries, n=args.n)
    print(format_dashboard(suite))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("layer1", help="run Layer 1 tool evals")
    p1.add_argument("--tags", default="", help="comma-separated tag filter (e.g. smoke)")
    p1.add_argument("--include-writes", action="store_true",
                    help="also run write cases (isolated namespaces only)")
    p1.add_argument("--json", default="", help="write JSON report to this path")
    p1.set_defaults(fn=_cmd_layer1)

    p2 = sub.add_parser("judge", help="judge an existing output file N times")
    p2.add_argument("--jd", required=True)
    p2.add_argument("--output", required=True)
    p2.add_argument("--master", default="", help="master resume excerpt file (default: workspace)")
    p2.add_argument("-n", type=int, default=5)
    p2.set_defaults(fn=_cmd_judge)

    p3 = sub.add_parser("suite", help="full golden-dataset eval suite")
    p3.add_argument("-n", type=int, default=5, help="runs per golden entry")
    p3.add_argument("--entries", default="", help="comma-separated GD ids (default: all)")
    p3.set_defaults(fn=_cmd_suite)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
