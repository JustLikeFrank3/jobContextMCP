"""Layer 3 orchestration — the full eval suite.

For each golden entry: generate the output N times, judge every run,
aggregate variance metrics, and append a version-stamped results row.
Results land in ``evals/results/`` (gitignored) and each run is compared
to the previous one so score drift is visible immediately.

Re-run on any change to: master resume, prompt templates, model version,
or MCP tool logic.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from evals.golden import GoldenEntry, load_golden, resolve_file
from evals.judge import JudgeScore, judge_output
from evals.variance import RunAggregate, aggregate_runs

RESULTS_DIR = Path(__file__).parent / "results"

GenerateFn = Callable[[GoldenEntry, str], str]      # (entry, jd_text) → output text
JudgeFn = Callable[[str, str, str], JudgeScore]      # (jd, master_excerpt, output) → score


@dataclass
class EntryResult:
    entry_id: str
    role: str
    aggregate: RunAggregate | None = None
    error: str = ""

    def dashboard_row(self) -> dict:
        """One row of the doc's results table."""
        if self.aggregate is None:
            return {"gd_id": self.entry_id, "role": self.role, "error": self.error}
        dims = self.aggregate.per_dimension
        return {
            "gd_id": self.entry_id,
            "role": self.role,
            "keyword": round(dims["keyword_coverage"]["mean"], 2),
            "relevance": round(dims["relevance"]["mean"], 2),
            "accuracy": round(dims["accuracy"]["mean"], 2),
            "impact": round(dims["impact_language"]["mean"], 2),
            "ats": round(dims["ats_readiness"]["mean"], 2),
            "mean": round(self.aggregate.mean_score, 2),
            "cov_pct": round(self.aggregate.cov_pct, 1),
            "flip_rate_pct": round(self.aggregate.flip_rate_pct, 1),
            "alerts": self.aggregate.alerts,
        }


@dataclass
class SuiteResult:
    n_runs: int
    entries: list[EntryResult] = field(default_factory=list)
    started_at: str = ""
    git_sha: str = ""
    provider: str = ""

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "git_sha": self.git_sha,
            "provider": self.provider,
            "n_runs": self.n_runs,
            "rows": [e.dashboard_row() for e in self.entries],
            "detail": {
                e.entry_id: e.aggregate.to_dict()
                for e in self.entries if e.aggregate is not None
            },
        }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).parent, check=False,
        ).stdout.strip()
    except OSError:
        return ""


def default_generate(entry: GoldenEntry, jd_text: str) -> str:
    """Generate through the real production path (tools.generate).

    Outputs are saved under an EVAL-prefixed filename so eval artifacts are
    recognizable in the workspace and never overwrite real application
    materials.
    """
    from lib import config  # noqa: PLC0415 — lazy: imports server config + LLM client
    from tools import generate  # noqa: PLC0415

    output_filename = f"EVAL {entry.id} {entry.company} {entry.role}"
    if entry.output_kind == "cover_letter":
        status = generate.generate_cover_letter(
            entry.company, entry.role, jd_text, output_filename=output_filename
        )
        out_dir = config.get_active_cover_letters_dir()
    else:
        status = generate.generate_resume(
            entry.company, entry.role, jd_text, output_filename=output_filename
        )
        out_dir = config.get_active_optimized_resumes_dir()
    # generate_* returns a status report; the document itself is saved to the
    # workspace. A missing ✓ means generation fell back or errored — fail the
    # run rather than judging a status message.
    if not status.lstrip().startswith("✓"):
        raise RuntimeError(f"generation did not complete: {status[:300]}")
    return (out_dir / f"{output_filename}.txt").read_text(encoding="utf-8")


# qwen3-jobcontext runs a 40K-token context; the full ~30K-char master fits.
# Truncating to 6K made 80% of the master invisible and the judge flagged
# real (unseen) claims as hallucinations.
def _master_excerpt(max_chars: int = 32000) -> str:
    from tools import resume  # noqa: PLC0415 — lazy: imports server config

    return resume.read_master_resume()[:max_chars]


def run_entry(
    entry: GoldenEntry,
    n: int = 5,
    generate_fn: GenerateFn | None = None,
    judge_fn: JudgeFn | None = None,
) -> EntryResult:
    """Generate + judge one golden entry N times."""
    jd_path = resolve_file(entry.jd_file)
    if jd_path is None:
        return EntryResult(entry.id, entry.role, error=f"JD file not found: {entry.jd_file}")
    jd_text = jd_path.read_text(encoding="utf-8")
    generate = generate_fn or default_generate
    judge = judge_fn or (
        lambda jd, master, output: judge_output(jd, master, output)
    )
    master = _master_excerpt()
    scores: list[JudgeScore] = []
    errors: list[str] = []
    for i in range(n):
        try:
            output = generate(entry, jd_text)
            scores.append(judge(jd_text, master, output))
        except Exception as e:
            errors.append(f"run {i + 1}: {type(e).__name__}: {e}")
    if not scores:
        return EntryResult(entry.id, entry.role, error="; ".join(errors) or "no runs completed")
    result = EntryResult(entry.id, entry.role, aggregate=aggregate_runs(scores))
    if errors:
        result.error = "; ".join(errors)
    return result


def run_suite(
    entries: list[GoldenEntry] | None = None,
    n: int = 5,
    generate_fn: GenerateFn | None = None,
    judge_fn: JudgeFn | None = None,
    results_dir: Path | None = None,
) -> SuiteResult:
    """Run the full suite and persist a version-stamped results file."""
    from lib.config import llm_generation_status  # noqa: PLC0415

    provider, _ready = llm_generation_status()
    suite = SuiteResult(
        n_runs=n,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        git_sha=_git_sha(),
        provider=provider,
    )
    for entry in entries if entries is not None else load_golden():
        suite.entries.append(run_entry(entry, n=n, generate_fn=generate_fn, judge_fn=judge_fn))
    save_results(suite, results_dir)
    return suite


def save_results(suite: SuiteResult, results_dir: Path | None = None) -> Path:
    out_dir = results_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = suite.started_at.replace(":", "").replace("-", "").replace("T", "-") or "unstamped"
    path = out_dir / f"results-{stamp}.json"
    suffix = 2
    while path.exists():  # two runs in the same second must not clobber each other
        path = out_dir / f"results-{stamp}-{suffix}.json"
        suffix += 1
    payload = suite.to_dict()
    previous = latest_results(out_dir, before=path)
    if previous is not None:
        payload["baseline"] = str(previous[0].name)
        payload["baseline_delta"] = _delta(payload, previous[1])
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def latest_results(
    results_dir: Path | None = None, before: Path | None = None
) -> tuple[Path, dict] | None:
    out_dir = results_dir or RESULTS_DIR
    if not out_dir.exists():
        return None
    files = sorted(
        (p for p in out_dir.glob("results-*.json") if p != before),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return None
    newest = files[-1]
    try:
        return newest, json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _delta(current: dict, baseline: dict) -> dict:
    """Per-entry mean/keyword deltas vs. the previous run."""
    base_rows = {r.get("gd_id"): r for r in baseline.get("rows", [])}
    deltas: dict[str, dict] = {}
    for row in current.get("rows", []):
        base = base_rows.get(row.get("gd_id"))
        if not base or "mean" not in row or "mean" not in base:
            continue
        keyword_delta = round(row["keyword"] - base["keyword"], 2)
        deltas[row["gd_id"]] = {
            "mean": round(row["mean"] - base["mean"], 2),
            "keyword": keyword_delta,
            "keyword_regression": keyword_delta < -0.5,
        }
    return deltas


def format_dashboard(suite: SuiteResult) -> str:
    """The doc's sample results table, as fixed-width text."""
    header = (
        f"{'GD-ID':6} {'Role':28} {'Keyword':>7} {'Relev.':>6} {'Accur.':>6} "
        f"{'Impact':>6} {'ATS':>5} {'Mean':>5} {'CoV%':>5} {'Flip%':>5}"
    )
    lines = [header, "─" * len(header)]
    for e in suite.entries:
        row = e.dashboard_row()
        if "error" in row and "mean" not in row:
            lines.append(f"{row['gd_id']:6} {row['role'][:28]:28} ERROR: {row['error']}")
            continue
        lines.append(
            f"{row['gd_id']:6} {row['role'][:28]:28} {row['keyword']:>7} "
            f"{row['relevance']:>6} {row['accuracy']:>6} {row['impact']:>6} "
            f"{row['ats']:>5} {row['mean']:>5} {row['cov_pct']:>5} {row['flip_rate_pct']:>5}"
        )
        for alert in row.get("alerts", []):
            lines.append(f"       ⚠ {alert}")
    return "\n".join(lines)
